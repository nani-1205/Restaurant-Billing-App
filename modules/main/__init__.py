# modules/menu/__init__.py
from flask import Blueprint
# Adjust template folder path relative to the location of this __init__.py file
bp = Blueprint('menu', __name__, template_folder='../../templates/menu')
from . import routes