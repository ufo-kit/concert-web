import concert.session.management as csm
from concert.devices.base import Device
from concert_web import app
from flask import render_template, abort


class DeviceInstance(object):
    def __init__(self, instance_name, instance):
        self.name = instance_name
        self.device = instance


@app.route('/')
def index():
    return render_template('index.html', sessions=csm.get_existing())


@app.route('/session/<name>')
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
    instances = [v for v in public_vars if isinstance(v.device, Device)]

    return render_template('session.html', instances=instances)
