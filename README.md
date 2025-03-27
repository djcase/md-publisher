# Metadata Publishing Service

## Endpoints

### /mdjson
Methods: POST OPTIONS

Arguments: None

Replace mdJSON on the associated ScienceBase item. The mdJSON is translated into sbJSON by sending
it through the mdTranslator. Then, the matching item is found in ScienceBase and updated with the
posted mdJSON.

### /mdjson/<string:item_id>
Methods: GET PUT 

Arguments: item_id

Get mdJSON from ScienceBase for the given item_id. PUT will also replace the mdJSON file on the item.

### /product
Methods: POST 

Arguments: None

Create a product in ScienceBase from mdJSON

### /product/<string:item_id>
Methods: PUT

Arguments: item_id

Update a product in ScienceBase from mdJSON

### /product/<string:item_id>
Methods: DELETE

Arguments: item_id

Delete a project and its child items from ScienceBase

### /project
Methods: POST

Arguments: None

Create a project in ScienceBase from mdJSON.

### /project/<string:item_id>
Methods: PUT

Arguments: item_id

Update a project in ScienceBase from mdJSON

### /project/<string:item_id>
Methods: DELETE

Arguments: item_id

Delete a project and its child items from ScienceBase

### /version
Methods: GET

Arguments: None

Returns the current service version

## Dependencies

This service depends on the mdTranslator-rails service for translating mdJSON to sbJSON and
ISO-19115-2. See https://github.com/adiwg/mdTranslator

## Development

### To build the container from this folder
```bash
docker build -t md-publisher .
```

### To run the container
```bash
docker run -p 5000:5000 md-publisher
```

### Legacy setup instructions from the README of the original project

#### Set up the environment
1. Create a Python 3 virtual environment in the venv directory `virtualenv venv`
2. Activate the virtual environment `. venv/bin/activate`
3. Install dependencies `pip install -r requirements-dev.txt`
4. Fix autodoc `. fix_flask_autodoc.sh`

#### Run the service locally
`FLASK_APP=md-publisher.py venv/bin/flask run`

#### Run the service locally using WSGI
`MD_PUBLISHER_ROOT=. venv/bin/uwsgi --http :5000 --wsgi-file md-publisher.wsgi`

#### Run the unit tests
`venv/bin/python tests.py`
