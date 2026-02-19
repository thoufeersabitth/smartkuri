from builtins import TypeError, ValueError, float
from django import template

register = template.Library()

@register.filter(name='inr')
def inr(value):
    try:
        value = float(value)
        return f"₹{value:,.2f}"
    except (ValueError, TypeError):
        return "₹0.00"
