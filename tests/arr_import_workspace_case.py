"""Render synthetic import UI for browser acceptance; no Arr or production reads."""
from pathlib import Path
import sys
from flask import Flask, render_template


def render():
    root = Path(__file__).resolve().parents[1]
    app = Flask(__name__, template_folder=str(root/'app/templates'))
    with app.test_request_context('/arr-imports'):
        return render_template('arr-imports.html', csrf='synthetic-csrf',
            viewer={'admin': True, 'name': 'Synthetic operator'})


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(render())
