from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Return dictionary[key], or 0 if missing (for student_amounts lookup)."""
    return dictionary.get(key, 0)
