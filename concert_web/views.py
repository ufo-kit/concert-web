import concert.session.management as csm
from concert.devices.base import Device
from concert.base import HardLimitError
from concert.quantities import q
from concert_web import app
from flask import render_template, abort, request
import traceback
import StringIO
import json
import sys


class DeviceInstance(object):
    def __init__(self, instance_name, instance):
        self.name = instance_name
        self.device = instance


class Session(object):
    def __init__(self, name, module, instances):
         self.name = name
         self.module = module
         self.instances = instances

sessions = {}


@app.route('/')
def index():
    return render_template('index.html', sessions=csm.get_existing())


@app.route('/session/<name>', methods=['GET'])
def session(name):
    if not csm.exists(name):
        app.logger.warning('{} does not exist'.format(name))
        abort(404)

    try:
        app.logger.info('Loading {}'.format(name))
        module = csm.load(name)
    except Exception as e:
        app.logger.error(str(e))
        abort(501)

    global devices
    public_vars = [DeviceInstance(v, getattr(module, v)) for v in dir(module) if not v.startswith('_')]
    instances = { v.name: v for v in public_vars if isinstance(v.device, Device) }
    devices = instances.keys()
    sessions[name] = Session(name, module, instances)

    return render_template('session.html', session_name=name, instances=instances.values())


unit_q = {
    '1.0 1 / second': "/q.s",
    '1 pixel': "*q.pixel",
    '1 second': "*q.s",
    '1 micrometer': "*q.micrometer",
    '1 millimeter': "*q.mm",
    '': ""
}

def get_exec_output(name, code):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    code_out = StringIO.StringIO()
    sys.stdout = code_out
    exec code in globals(), exec_globals
    sys.stdout = sys.__stdout__
    s = code_out.getvalue()
    code_out.close()
    return str(s)


@app.route('/change/<name>', methods=['POST'])
def change(name):
    if not name in sessions:
        app.logger.error("{} not started yet".format(name))
        abort(501)

    session = sessions[name]
    data_to_change = request.get_json(force=True)
    device_name = data_to_change['device']
    property_name = data_to_change['name']
    value = data_to_change['value']
    device = session.instances[device_name].device[property_name]
    changed_data = {'error': '', 'hardlimit': 'False'}

    def execute(future):
        exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
        try:
            exec line in globals(), exec_globals
        except NameError:
            value = str(value)
        except HardLimitError as herror:
            changed_data['error'] = str(herror)
            changed_data['hardlimit'] = "True"
            pass

    try:
        unit = device.unit
        line = str(device_name + "." + property_name + " = " + str(value) + unit_q[str(unit)])
        if str(unit) == "1.0 1 / second":
            value = float(value)
        future = device.set(value * unit)
        future.add_done_callback(execute)
        return json.dumps(changed_data)

    except NameError:
        value = str(value)
        line = str(device_name + "." + property_name + " = " + value + unit_q[str(unit)])
        future = device.set(value * unit)
        future.add_done_callback(execute)
        return json.dumps(changed_data)

    except AttributeError:
        line = str(device_name + "." + property_name + " = '" + value + "'")
        future = device.set(value)
        future.add_done_callback(execute)
        return json.dumps(changed_data)


@app.route('/terminal/<name>', methods=['POST'])
def handle_line(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    line = request.get_json(force=True)
    line_json = {'output': '' , 'device': '', 'name': '', 'value': '',
                 'hardlimit': 'False', 'traceback': ''}

    try:
        if "=" in line['execute']:
            before, sep, after = line['execute'].rpartition("=")
            device, point, name = before.rpartition(".")
            if "*" in after:
                val, mult, unit = after.rpartition("*")
            elif "/" in after:
                val, div, unit = after.rpartition("/")
            else:
                val = after
            line_json['device'] = device
            line_json['name'] = name
            line_json['value'] = val.replace(" ", "")
            exec(line['execute'], globals(), exec_globals)
        elif "(" in line['execute']:
            exec(line['execute'], globals(), exec_globals)
        else:
            print_line = str("print " + line['execute'])
            line_json['output'] = get_exec_output(name, print_line)

        return json.dumps(line_json)

    except HardLimitError as herror:
        line_json['hardlimit'] = "True"
        line_json['output'] = str(herror)
        return json.dumps(line_json)

    except:
        exc = traceback.format_exc()
        line_json['traceback'] = exc
        return json.dumps(line_json)


@app.route('/data_for_terminal/<name>', methods=['POST'])
def get_data_from_gui(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    data_from_gui = request.get_json(force=True)
    hard_limit_json = {'device': '', 'state': ''}

    for x in data_from_gui:
        if (len(x) == 4 and len(x[2]) > 0):
            line = str(x[0] + "." + x[1] + " = " + x[2] + unit_q[str(x[3])])
            try:
                exec(line, globals(), exec_globals)
            except NameError as e:
                pass
            except HardLimitError as herror:
                state_code = "print " + x[0] + ".state"
                hard_limit_json['state'] = get_exec_output(name, state_code)
                hard_limit_json['device'] = x[0]
                pass

    return json.dumps(hard_limit_json)


@app.route('/tab_complete/<name>', methods=['GET'])
def get_tab_completion(name):
    completion_str = ""
    completion = ""
    for device in devices:
        code = "print ','.join(dir(" + device + "))"
        s = get_exec_output(name, code)
        dir_device = s.split(',')
        dir_device = [x for x in dir_device if not x.startswith("_")]
        dir_device = [device + "." + str(x) for x in dir_device]
        dir_device = [x.replace('\n', '') for x in dir_device]
        completion_str += ','.join(dir_device) + ","
        completion = completion_str.split(",")

    return json.dumps(completion)


@app.route('/get_methods/<name>', methods=['GET'])
def get_methods(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    d = dict(exec_globals, **globals())
    methods_array = []
    for device in devices:
        code_out = StringIO.StringIO()
        sys.stdout = code_out
        code = """
names = dir(""" + device + """)
attrs = {name: getattr(""" + device + """, name) for name in names}
funcs = {name: attr for name, attr in attrs.items() if hasattr(attr, '__call__') and not       name.startswith('_') and not name.startswith('get_') and not name.startswith('set_') }
print sorted(funcs.keys())
"""
        exec (code, d, d)
        sys.stdout = sys.__stdout__
        dev_methods = code_out.getvalue()
        char_arr = ['\n', '[', ']', ' ', "'", '"']
        for x in char_arr:
            dev_methods = dev_methods.replace(x, "")
        methods_array.append(dev_methods)

    methods = zip(devices, methods_array)
    return json.dumps(methods)


@app.route('/upper_lower/<name>', methods=['GET'])
def get_upper_lower(name):
    up_low_devs = []
    for device in devices:
        code = "print dir(" + device + ")"
        names = get_exec_output(name, code)
        if "lower" in names:
            lower_code = "print " + device + ".lower.magnitude"
            lower = get_exec_output(name, lower_code)
            up_low_devs.append({'device': device, 'lower': lower})
        if "upper" in names:
            upper_code = "print " + device + ".upper.magnitude"
            upper = get_exec_output(name, upper_code)
            up_low_devs.append({'device': device, 'upper': upper})

    return json.dumps(up_low_devs)


@app.route('/method/<name>', methods=['POST'])
def exec_method(name):
    to_do = request.get_json(force=True)
    method_json = {'output': '', 'traceback': '', 'device': '', 'state': ''}

    try:
        method_json['output'] = get_exec_output(name, to_do['method'])
        if "start_recording()" in to_do['method'] or "stop_recording()" in to_do['method']:
            device = str(to_do['method'].split(".")[0])
            try:
                state_code = "print " + device + ".state"
                method_json['device'] = device
                method_json['state'] = get_exec_output(name, state_code)
            except:
                pass

    except:
        exc = traceback.format_exc()
        method_json['traceback'] = exc
        pass

    return json.dumps(method_json)


@app.route('/lock_unlock/<name>', methods=['POST'])
def lock_unlock(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    data = request.get_json(force=True)
    exec (data["method"], globals(), exec_globals)
    return name
