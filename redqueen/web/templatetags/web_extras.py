from django import template

register = template.Library()


@register.filter
def unscore(value):
    """community_service -> community service"""
    return str(value).replace('_', ' ')


BANNER_CANDIDATES = ('web/banner.jpg', 'web/banner.jpeg', 'web/banner.png', 'web/banner.webp')


@register.simple_tag
def banner_url():
    """Login banner: the first of web/banner.{jpg,jpeg,png,webp} that exists, else the bundled SVG."""
    from django.contrib.staticfiles import finders
    from django.templatetags.static import static

    for candidate in BANNER_CANDIDATES:
        if finders.find(candidate):
            return static(candidate)
    return static('web/banner.svg')
