run: dist
	cd dist && FLASK_APP=md-publisher.py ../venv/bin/flask run

tests:
	venv/bin/python tests.py

clean:
	rm -rf dist
	
dist: clean	
	mkdir dist
	cp -R md-publisher.wsgi md-publisher.py config static templates requirements.txt fix_flask_autodoc.sh dist

wsgi:
	MD_PUBLISHER_ROOT=. uwsgi --http :5000 --wsgi-file md-publisher.wsgi

setup:
	venv/bin/pip install -r requirements-dev.txt
	. fix_flask_autodoc.sh
