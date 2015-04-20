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
import re


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

    public_vars = [DeviceInstance(v, getattr(module, v)) for v in dir(module) if not v.startswith('_')]
    instances = { v.name: v for v in public_vars if isinstance(v.device, Device) }
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


@app.route('/change/<name>', methods=['POST'])
def change(name):
    if not name in sessions:
        app.logger.error("{} not started yet".format(name))
        abort(501)

    session = sessions[name]
    data = request.get_json(force=True)
    device_name, property_name, value = data['device'], data['name'], data['value']
    device = session.instances[device_name].device[property_name]

    try:
        unit = device.unit
        line = str(device_name + "." + property_name + " = " + value + unit_q[str(unit)])
        if str(unit) == "1.0 1 / second":
            value = float(value)
        future = device.set(value * unit)
    except AttributeError:
        if (property_name == "trigger_mode" and value == ''):
            value = "'AUTO'"
        line = str(device_name + "." + property_name + " = " + value)
        future = device.set(value)
    except ValueError as verror:
        data['error'] = str(verror)
        return json.dumps(data)

    if future.done():
        exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
        try:
            exec(line, globals(), exec_globals)
        except HardLimitError as herror:
            pass

    return json.dumps(data)


@app.route('/tab_complete/<name>', methods=['GET'])
def get_tab_completion(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}

    completion_str = ''
    devices = ["camera", "ring", "motor"]
    for device in devices:
        output = StringIO.StringIO()
        sys.stdout = output
        exec("print ','.join(dir(" + device + "))", globals(), exec_globals)
        sys.stdout = sys.__stdout__
        s = output.getvalue()
        dir_device = s.split(',')
        dir_device = [x for x in dir_device if not x.startswith("_")]
        dir_device = [device + "." + str(x) for x in dir_device]
        dir_device = [x.replace('\n', '') for x in dir_device]
        completion_str += ','.join(dir_device) + ","
        completion = completion_str.split(",")
        output.close()

    return json.dumps(completion)


@app.route('/terminal/<name>', methods=['POST'])
def handle_line(name):
    exec_globals = {key: value.device for key, value in sessions[name].instances.items()}
    code_out = StringIO.StringIO()
    sys.stdout = code_out
    output = request.get_json(force=True)
    line = "first_request"
    answer = {'return': '' , 'device': '', 'name': '', 'value':'', 'position': '',
              'current': '', 'energy': '', 'lifetime': ''}

    if 'execute' not in output:
        for x in output:
            if (len(x) == 4 and len(x[2]) > 0):
                line = str(x[0] + "." + x[1] + " = " + x[2] + unit_q[str(x[3])])
                try:
                    exec(line, globals(), exec_globals)
                except HardLimitError as herror:
                    answer['position'] = str(herror)
                    for x in output:
                        if len(x) == 4:
                            if (len(x[2]) > 0 and x[1] != "position"):
                                line = str(x[0] + "." + x[1] + " = " + x[2] + unit_q[str(x[3])])
            else:
                line = str(x[0])

    if line == "first_request":
        line = output['execute']

    try:
        if "=" in line:
            before, sep, after = line.rpartition("=")
            device, point, name = before.rpartition(".")
            val = re.findall(r"[-+]?\d*\.\d+|\d+", str(after))

            answer['device'] = device
            answer['name'] = name
            answer['value'] = val
            exec(line, globals(), exec_globals)
        elif "(" in line:
            exec(line, globals(), exec_globals)
        else:
            new_line = str("print " + line)
            exec(new_line, globals(), exec_globals)

    except:
        exc = traceback.format_exc()
        answer['return'] = exc
        return json.dumps(answer)

    sys.stdout = sys.__stdout__
    s = code_out.getvalue()
    answer["return"] += "%s" % s
    code_out.close()

    if line == "ring":
        val = re.findall(r"[-+]?\d*\.\d+|\d+", answer["return"])
        answer['device'] = 'ring'
        answer['current'] = val[0]
        answer['energy'] = val[1]
        answer['lifetime'] = val[2]
    elif "ring.current" in line:
        val = re.findall(r"[-+]?\d*\.\d+|\d+", answer["return"])
        answer['current'] = val
    elif "ring.energy" in line:
        val = re.findall(r"[-+]?\d*\.\d+|\d+", answer["return"])
        answer['energy'] = val
    elif "ring.lifetime" in line:
        val = re.findall(r"[-+]?\d*\.\d+|\d+", answer["return"])
        answer['lifetime'] = val

    return json.dumps(answer)
