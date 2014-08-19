import jinja2
from concert_web import app


@app.template_filter('unit_to_html')
def unit_filter(value):
    if value is not None and not isinstance(value, jinja2.runtime.Undefined):
        return '{:H}'.format(value.units)

    return ''
