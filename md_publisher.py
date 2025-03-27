""" md-publisher.py is a flask application providing services to update ScienceBase items via mdJSON """
from flask_autodoc import Autodoc
from flask import Flask, jsonify, abort, make_response, request, logging
from flask_cors import CORS
from sciencebasepy import SbSession
from dateutil import parser
import ast
import json
import os
import requests
import re
import sys
import traceback
import logging
import bson
import certifi

VERSION = '1.5.0'
app = Flask(__name__)
app.url_map.strict_slashes = False
auto = Autodoc(app)
CORS(app, resources={r"/*": {"origins": "*"}})

MD_PUBLISHER_ROOT = os.environ['MD_PUBLISHER_ROOT'] if 'MD_PUBLISHER_ROOT' in os.environ else '.'
app.config.from_pyfile(MD_PUBLISHER_ROOT + '/config/config.py')

ISO_19115_1 = 'iso19115_1'
ISO_19115_2 = 'iso19115_2'
MDJSON = 'mdJson'
SBJSON = 'sbJson'

COPY_SBID = 'sciencebase-production-id'
LCC_SBID = 'gov.sciencebase.catalog'
LCC_SBID2 = 'gov.sciencbase.catalog'

LCC_IDENTIFIERS = [COPY_SBID, LCC_SBID, LCC_SBID2]
SB_IDENTIFIERS = [LCC_SBID, LCC_SBID2]

PROJECT_RESOURCE_TYPE = 'project'
PRODUCT_RESOURCE_TYPE = 'product'
RESOURCE_TYPES = [PROJECT_RESOURCE_TYPE, PRODUCT_RESOURCE_TYPE]

_sb_session = None
_session = None

# Dict of ItemLink type IDs -- used when creating relationships
_item_link_types = None

ITEM_FIELDS = "id,parentId,title,identifiers,facets,files,tags,extents,provenance,dates,contacts,ancestors"

@app.before_first_request
def setup_logging():
    if not app.debug:
        # In production mode, add log handler to sys.stderr.
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        app.logger.addHandler(handler)
        app.logger.setLevel(app.config['LOGGING_LEVEL'])

@app.route('/', methods=['GET'])
def index():
    return auto.html(title='Metadata Publishing Service version %s' % VERSION, template='fws.html')

@app.route('/version', methods=['GET'])
@auto.doc()
def version():
    """Returns the current service version"""
    return jsonify({'version': VERSION})

@app.route('/mdjson/<string:item_id>', methods=['GET', 'PUT'])
@auto.doc()
def get_md_json_for_sb_item(item_id):
    """Get mdJSON from ScienceBase for the given item_id. PUT will also replace the mdJSON file on the item."""
    sb_json = get_sb_session(request).get_item(item_id)
    sb_json = fix_sbjson(sb_json)

    # First check if it has an mdjson file
    md_json = get_mdjson_from_file(sb_json)

    # If nothing was found, return md_json from the translator
    if md_json is None:
        md_json = translate_json(sb_json)
        
    # On PUT, replace the mdjson and iso files on the item
    if request.method == 'PUT':
        response = upsert_item_and_upload_metadata(sb_json, md_json)
        if 'error' in response:
            md_json = response

    return api_response(md_json)

@app.route('/mdjson', methods=["POST"])
@auto.doc()
def replace_md_json():
    """Replace mdJSON on the associated ScienceBase item"""
    return api_response(update_metadata_json(get_mdjson(request)))

@app.route('/project', methods=['POST'])
@auto.doc()
def create_project():
    """Create a project in ScienceBase from mdJSON."""
    return api_response(create_or_update_item(get_mdjson(request)))

@app.route('/product', methods=['POST'])
@auto.doc()
def create_product():    
    """Create a product in ScienceBase from mdJSON"""
    return api_response(create_or_update_item(get_mdjson(request)))

@app.route('/project/<string:item_id>', methods=['PUT'])
@auto.doc()
def update_project(item_id):
    """Update a project in ScienceBase from mdJSON"""
    return api_response(create_or_update_item(get_mdjson(request), item_id))

@app.route('/product/<string:item_id>', methods=['PUT'])
@auto.doc()
def update_product(item_id):   
    """Update a product in ScienceBase from mdJSON""" 
    return api_response(create_or_update_item(get_mdjson(request), item_id))

@app.route('/project/<string:item_id>', methods=['DELETE'])
@auto.doc()
def delete_project(item_id): 
    """Delete a project and its child items from ScienceBase"""
    return api_response(delete_item(item_id, 'Project'))

@app.route('/product/<string:item_id>', methods=['DELETE'])
@auto.doc()
def delete_product(item_id):        
    """Delete a project and its child items from ScienceBase"""
    return api_response(delete_item(item_id))

@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({"error": {"messages":["Not found"]}}), 404)

@app.errorhandler(500)
def internal_error(error):
    return make_response(jsonify({"error": {"messages":["Error processing request"]}}), 400)

@app.errorhandler(Exception)
def handle_exceptions(error):
    traceback.print_exc(file=sys.stdout)
    status_code = None
    errmsg = u'{0}'.format(error).encode('ascii','ignore').decode('ascii')

    sciencebasepy_error_regex = re.compile(r".*?:\s*(\d*)\s*:\s*(\{.*\}).*$")
    m = re.match(sciencebasepy_error_regex, errmsg)
    if m:
        status_code = int(m.group(1))
        errmsg = json.loads(m.group(2))
    else:
        status_code = 400
        errmsg = {"error": {"messages":[errmsg]}}

    response = jsonify(errmsg)   
    response.status_code = status_code 

    return response

def get_mdjson(request):
    ret = {}
    if request.json:
        if 'data' in request.json:
            ret = request.json['data']
        else:
            ret = request.json
    return ret    

def get_sb_session(request):
    """Get sciencebasepy session based on user credentials in 
    :param request: Flask request
    :return: sciencebasepy session
    """
    app.logger.debug('get_sb_session')
    global _sb_session
    if _sb_session is None:
        _sb_session = SbSession(app.config['SCIENCEBASE_ENV'])
    if request:
        token = {}
        request_data = get_mdjson(request)
        if 'access_token' in request_data:
            token['access_token'] = request_data['access_token']
        if 'refresh_token' in request_data:
            token['refresh_token'] = request_data['refresh_token']
        if bool(token):
            _sb_session.add_token(token)
    return _sb_session

def get_session():
    """Get requests session 
    :return: Requests session
    """
    app.logger.debug('get_session')
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({'Accept': 'application/json'})
    return _session

def translate_json(source_json, destination_format = None): 
    """Translate between sbJSON and mdJSON through the 
    :param source_json: Source JSON
    :param destination_format: Destination format (defaults to mdJSON)
    :return Translated JSON, or an error message
    """  
    app.logger.debug('translate_json') 

    ret = None

    source_format = None
    if 'schema' in source_json and 'name' in source_json['schema'] and source_json['schema']['name'] == MDJSON:
        source_format = MDJSON
        if destination_format is None:
            destination_format = SBJSON
    else:
        source_format = SBJSON
        if destination_format is None:
            destination_format = MDJSON
    options = {
        u'writer': destination_format, 
        u'reader': source_format, 
        u'validate': u'none' if source_format == SBJSON else u'normal',
        u'format': u'json', 
        u'file': json.dumps(source_json)
    }  

    # cert_file_path = "/etc/httpd/conf/ssl.crt/star_sciencebase_gov.crt"
    # key_file_path = "/etc/httpd/conf/ssl.key/star_sciencebase_gov.key"
    # root_cert = '/etc/httpd/conf/ssl.crt/DigiCertCA.crt'
    # cert = (cert_file_path, key_file_path)

    r = get_session().post(app.config['MDTRANSLATOR_URL'], data=options)
    if (r.status_code != 200):
        ret = {'error': {'messages': ['HTTP %d: %s' % (r.status_code, r.text)]}}
    else:
        ret = r.json()
        if 'success' in ret and ret['success'] and 'data' in ret:
            if destination_format == MDJSON or destination_format == SBJSON:
                ret = json.loads(ret['data'])
            else:
                ret = ret['data']
        elif 'success' in ret and not ret['success']:
            messages = {"error": {"messages": ["Error transforming to %s" % destination_format]}}
            if not ret['messages']['readerStructurePass']:
                msgs = ret['messages']['readerStructureMessages']
                if len(msgs) > 1:
                    try:
                        msgs = json.loads(msgs[1])
                    except:
                        pass
                messages['error']['messages'].extend([m for m in msgs])
            if not ret['messages']['readerValidationPass']:
                msgs = ret['messages']['readerValidationMessages']
                if len(msgs) > 1:
                    try:
                        msgs = json.loads(msgs[1])
                    except:
                        pass
                messages['error']['messages'].extend([m for m in msgs])
            if not ret['messages']['readerExecutionPass']:
                messages['error']['messages'].extend(ret['messages']['readerExecutionMessages'])
            ret = messages
        elif not 'title' in ret or not ret['title']:
            ret = {"error": {"messages":["Empty response from mdTranslator"]}}
        else:
            raise Exception(ret)
    return ret

def fix_sbjson(sbjson):
    """Make required changes to the sbJSON to ensure correctness.
    :param sbjson: sbJSON to fix
    :return: Fixed sbJSON
    """
    app.logger.debug('fix_sbjson')

    if 'contacts' in sbjson:
        new_contacts = []
        for contact in sbjson['contacts']:
            if 'contactType' not in contact:
                contact['contactType'] = 'person'
            new_contacts.append(contact)
        sbjson['contacts'] = new_contacts
    if 'identifiers' in sbjson:
        new_identifiers = []
        for identifier in sbjson['identifiers']:
            if 'scheme' not in identifier:
                identifier['scheme'] = identifier['type'] if 'type' in identifier and identifier['type'] else 'adiwg'
            if 'type' not in identifier:
                identifier['type'] = identifier['scheme']
            new_identifiers.append(identifier)
        sbjson['identifiers'] = new_identifiers
    if 'dates' in sbjson:
        new_dates = []
        for d in sbjson['dates']:
            if 'T' in d['dateString']:
                dt = parser.parse(d['dateString'])
                d['dateString'] = dt.strftime("%Y-%m-%d %H:%M:%S")
            new_dates.append(d)
        sbjson['dates'] = new_dates
    app.logger.debug('exit fix_sbjson')
    return sbjson

def get_mdjson_from_file(sbjson):
    """Get msJSON from an attached file on ScienceBase Item
    :param sbjson: ScienceBase Item 
    :return: Updated ScienceBase Item JSON
    """
    app.logger.debug('get_mdjson_from_file')
    ret = None
    if sbjson and 'files' in sbjson:
        for sbfile in sbjson['files']:
            if sbfile['name'] == app.config['MDJSON_FILENAME']:
                try:
                    ret = ''
                    r = get_sb_session(request)._session.get(sbfile['url'], stream=True)
                    for line in r.iter_lines():
                        # filter out keep-alive new lines
                        if line:
                            ret += (line.decode('utf-8'))
                    ret = json.loads(ret)
                except:
                    app.logger.error('Failed to parse attached mdJSON')
    return ret

def upsert_item_and_upload_metadata(item, md_json):
    """Create or update a ScienceBase Item, and upload metadata files to it
    :param item: ScienceBase Item JSON
    :param mdjson: mdJSON 
    :return: Updated ScienceBase Item JSON
    """
    app.logger.debug('upsert_item_and_upload_metadata')
    ret = None
    iso1 = None
    iso2 = None
    files = []

    try:
        iso1 = translate_json(md_json, ISO_19115_1)
        iso2 = translate_json(md_json, ISO_19115_2)
    except:
        pass
    
    iso1_fname = app.config['ISO1_FILENAME']
    iso2_fname = app.config['ISO2_FILENAME']
    for fname, contents in [(app.config['MDJSON_FILENAME'], md_json), (iso1_fname, iso1), (iso2_fname, iso2)]:
        if contents:
            # Remove any existing files of the same name
            if 'files' in item: 
                sbfiles = []
                for sbfile in item['files']:
                    if not sbfile['name'] == fname:
                        sbfiles.append(sbfile)
                item['files'] = sbfiles

            # Stage the new file
            mime_type = None
            if isinstance(contents, dict):
                contents = json.dumps(contents)
                mime_type = "application/json"
            elif fname == iso1_fname:
                mime_type = "application/vnd.iso.19139-1+xml"
            elif fname == iso2_fname:
                mime_type = "application/vnd.iso.19139-2+xml"
            files.append(("file", (fname, contents.encode('utf-8'), mime_type)))
        else:
            app.logger.debug("FILE %s HAS NO CONTENTS" % fname)
            

    data = {"item": json.dumps(item)}
    if "id" in item and item["id"]:
        data["id"] = item["id"]

    sb = get_sb_session(request)
    try:
        response = sb._session.post(sb._base_upload_file_url, files=files, params={'scrapeFile':'false'}, data=data)
        ret = sb._get_json(response)
    except Exception as e:
        msg = 'Unable to upload %s' % (fname)
        app.logger.error(msg)
        ret = {"error": {"messages": [msg, "{0}".format(e)]}}

    return ret

def get_valid_identifier(identifier):
    """Verify identifier is an ObjectId, and strip off any request parameters
    :param identifier: Itentifier to parse
    :return: Valid ScienceBase Item identifier, or None if it is invalid
    """
    app.logger.debug("get_valid_identifier")
    ret = None
    if identifier:
        if bson.ObjectId().is_valid(identifier):
            ret = identifier
        else:
            split = identifier.split('?')
            if len(split) > 1:
                if bson.ObjectId().is_valid(split[0]):
                    ret = split[0]
    return ret

def create_or_update_item(md, item_id = None):
    """Create or update the ScienceBase Item from mdJSON
    :param md: mdJSON
    :param item_id: ID of the ScienceBase Item to update
    :return: Resulting ScienceBase Item JSON
    """
    app.logger.debug('create_or_update_item')
    ret = None
    mdjson = None

    parent_id = get_valid_identifier(md['parentid']) if 'parentid' in md else None
    community_id = md['community_id'] if 'community_id' in md else parent_id
    orphan_project_folder_id = md['projects_parent_id'] if 'projects_parent_id' in md else app.config['LC_MAP_ID']
    orphan_product_folder_id = md['products_parent_id'] if 'products_parent_id' in md else app.config['LC_MAP_ID']
    force = md['force_update'] if 'force_update' in md else app.config['FORCE_UPDATE']

    if 'mdjson' in md:
        mdjson = md['mdjson']
        item = create_or_update_sbitem_from_mdjson(item_id, parent_id, mdjson, community_id, orphan_project_folder_id, orphan_product_folder_id, force)
        ret = item
        if 'error' not in item:            
            if 'relationships' in md and len(md['relationships']) > 0:
                ret = [item]
                related_items = md['relationships']   
                for related_item in related_items:
                    product_item = create_or_update_sbitem_from_mdjson(None, item['id'], related_item, community_id, orphan_project_folder_id, orphan_product_folder_id, force)
                    create_item_link(sb, 'parentProject', 'productOf', item['id'], product_item['id'])
                    ret.append(product_item)                    
    else:
        ret = {"error": {"messages":["mdjson is required"]}}

    return ret

def get_parent_id(md_json, sb_json, base_folder_id, orphan_project_folder_id, orphan_product_folder_id):
    """Get the ScienceBase Item parent ID based on the given mdJSON and sbJSON if it is under the given base folder
    :param md_json: mdJSON
    :param sb_json: sbJSON
    :param base_folder_id: Base folder ID
    :return: Appropriate parent ID
    """
    app.logger.debug("get_parent_id")
    sb_parent_id = None

    # Use any existing parentId
    if sb_json and 'parentId' in sb_json and sb_json['parentId'] and is_ancestor(sb_json['parentId'], base_folder_id):
        sb_parent_id = sb_json['parentId']
    else:
        resource_type = get_resource_type(md_json)
        # Run through and search for parent ScienceBase item id if the item is a product        
        if resource_type == PRODUCT_RESOURCE_TYPE:
            result = find_sb_items({'identifiers': get_associated_project_identifiers(md_json)}, base_folder_id)
            if result and len(result) > 0:
                sb_parent_id = result[0]['id']
        if not sb_parent_id:
            if resource_type == PROJECT_RESOURCE_TYPE:
                sb_parent_id = orphan_project_folder_id
            else:
                sb_parent_id = orphan_product_folder_id        
    return sb_parent_id

def get_associated_project_identifiers(md_json):
    """Get the associated project identifiers from the mdJSON
    :param md_json: mdJSON
    :return: A list of project identifiers and types
    """
    app.logger.debug("get_associated_project_identifiers")
    ret = []
    if 'metadata' in md_json and 'associatedResource' in md_json['metadata']:
        for resource in md_json['metadata']['associatedResource']:            
            if 'associationType' in resource and resource['associationType'] == 'parentProject':
                ret.extend(get_resource_identifiers(resource))
    return ret

def get_resource_identifiers(resource):
    """Get resource identifiers from the given resource section from mdJSON
    :param resource: Resource mdJSON
    :return: A list of identifiers and types
    """
    app.logger.debug("get_resource_identifiers")
    ret = []
    citation = {}
    if 'metadataCitation' in resource:
        citation = resource['metadataCitation']
    elif 'resourceCitation' in resource:
        citation = resource['resourceCitation']
    elif 'citation' in resource:
        citation = resource['citation']
    if citation and 'identifier' in citation:
        for identifier in citation['identifier']:
            if 'namespace' in identifier and is_lcc_identifier(identifier['namespace']):
                id_key = None
                if identifier['namespace'] in SB_IDENTIFIERS:
                    id_key = get_valid_identifier(identifier['identifier'])
                else:
                    id_key = identifier['identifier']
                if identifier not in ret:
                    ret.append({"scheme": identifier["namespace"], "type": identifier["namespace"], "key": id_key})
    return ret

def create_or_update_sbitem_from_mdjson(item_id, parent_id, md_json, base_folder_id, orphan_project_folder_id, orphan_product_folder_id, force):
    """Create or update the specified ScienceBase item from the given mdJSON
    :param item_id: ID of an existing ScienceBase item
    :param parent_id: Parent ID under which to place the new or updated item
    :param md_json: mdJSON
    :param base_folder_id: Folder ID under which to look for the existing ScienceBase item
    :param force: If False, checks mdJSON on the existing item before updating. If True, always update.
    :return: ScienceBase Item JSON of the resulting Item
    """
    app.logger.debug("create_or_update_sbitem_from_mdjson")
    ret = {"error":{"messages": []}}
    sb = get_sb_session(request)    
    # Use the translator to convert the PTS mdJson to ScienceBase sbJson
    sb_json = fix_sbjson(translate_json(md_json))
    if 'error' in sb_json:
        title = ''
        if 'citation' in md_json.get('metadata', {}).get('resourceInfo', {}):
            title = md_json['metadata']['resourceInfo']['citation']['title']
        ret['error']['messages'].append("An error occurred translating mdJSON for record %s" % title)
        for message in sb_json['error']['messages']:
            ret['error']['messages'].append(message)
        return ret
    
    if get_resource_type(md_json) == PROJECT_RESOURCE_TYPE:
        add_browse_categories(sb_json, ['Project'])
        
    # Find if item exists, see whether merging or creating new item 
    if item_id:
        sb_json['id'] = item_id
    sb_found_record = find_sb_items(sb_json, base_folder_id)

    if len(sb_found_record) > 1:
        ret['error']['messages'].append('More than one instance found, skipping: %s ' % (str(sb_json['title'].encode('utf-8'))))
        return ret
    elif item_id and len(sb_found_record) == 0:
        ret['error']['messages'].append("No item found for specified ScienceBase identifier %s" % (item_id))
        return ret
    
    messages = []
    errors = []
    sb_item = None
    create_or_update = True
    if len(sb_found_record) == 1:     
        # The item exists in ScienceBase, and we need to merge
        msg = 'Exists in LCC Map Community: ' + str(sb_json['title'].encode('utf-8'))
        app.logger.info(msg)
        messages.append(msg)
        exist_sb_id = str(sb_found_record[0]['id'])

        # This is the existing SB item
        sb_item = sb.get_item(exist_sb_id, {'fields':ITEM_FIELDS})

        sb_item_date = sb_item['provenance']['dateCreated']
        if not force:
            # Obtain the mdJSON file for comparison before continuing
            md_open = get_mdjson_from_file(sb_item)
            if md_open and md_json == md_open:
                create_or_update = False
                msg = "Nothing new to update for: %s" % sb_item['id']
                app.logger.info(msg)
                messages.append(msg)
        if create_or_update:    
            # Obtain extent(s)
            sb_json['extents'] = geojson_to_sb_extent(md_json)
            # Merge the existing item into the sbJSON from the translator
            sb_json = merge_items(sb_item, sb_json)                           
    if create_or_update:        
        if not sb_item: 
            msg = 'No record exists in harvest community, creating new item in ScienceBase for: ' + str(sb_json['title'].encode('utf-8'))
            app.logger.info(msg)
            messages.append(msg)
            sb_json['id'] = None
            sb_json['extents'] = geojson_to_sb_extent(md_json)

        sb_json['parentId'] = parent_id if parent_id else get_parent_id(md_json, sb_json, base_folder_id, orphan_project_folder_id, orphan_product_folder_id)

        # Upload the mdJson as a file to the item
        # If an error uploading occurs, keep the sb_json we have so far and continue 
        response = upsert_item_and_upload_metadata(sb_json, md_json)
        if not 'error' in response:
            sb_json = response
            create_associated_links(sb_json['id'], md_json, base_folder_id)
            ret = sb_json
        else:
            logging.error(str(response))
            if 'messages' in response['error']:
                errors.extend(response['error']['messages'])
            else:
                errors.extend(response)

    if len(messages) > 0:
        ret['messages'] = messages
    if len(errors) > 0:
        ret['error'] =  {"messages": errors}

    return ret

def update_metadata_json(md_json,):
    app.logger.debug("update_metadata_json")
    ret = {"error":{"messages": []}}
    sb = get_sb_session(request)    
    # Use the translator to convert the PTS mdJson to ScienceBase sbJson
    sb_json = fix_sbjson(translate_json(md_json))
    if 'error' in sb_json:
        title = ''
        if md_json and 'metadata' in md_json and md_json['metadata'] and 'citation' in md_json['metadata'] and md_json['metadata']['citation'] and 'resourceInfo' in md_json['metadata']['citation']:
            title = md_json['metadata']['resourceInfo']['citation']['title']
        ret['error']['messages'].append("An error occurred translating mdJSON for record %s" % title)
        for message in sb_json['error']['messages']:
            ret['error']['messages'].append(message)
        return ret

    sb_found_record = find_sb_items(sb_json, app.config['LC_MAP_ID'])

    if len(sb_found_record) > 1:
        ret['error']['messages'].append('More than one instance found, skipping: %s ' % (str(sb_json['title'].encode('utf-8'))))
        return ret
    elif len(sb_found_record) == 0:
        title = ''
        if 'citation' in md_json.get('metadata', {}).get('resourceInfo', {}):
            title = md_json['metadata']['resourceInfo']['citation']['title']
        ret['error']['messages'].append("No ScienceBase item found for %s" % (title))
        return ret

    sb_item = sb.get_item(sb_found_record[0]['id'])
    response = upsert_item_and_upload_metadata(sb_item, md_json)
    if 'error' in response:
        logging.error(str(response))
        if 'messages' in response['error']:
            ret["error"]["messages"].extend(response['error']['messages'])
        else:
            ret["error"]["messages"].extend(response)

    return ret

def api_response(r):
    """Create an API response from the given value
    :param r: Response value
    :return: API response
    """
    app.logger.debug('api_response')
    ret = None
    ret_json = {}

    if r is None:
        ret_json = {"error": {"messages": ["An error occurred"]}}
        ret = jsonify(ret_json)
    elif isinstance(r, dict):
        ret_json = r
        ret = jsonify(ret_json)
    else:
        try:
            ret_json = ast.literal_eval(r)
            ret = jsonify(ret_json)            
        except ValueError as e:
            ret = jsonify(message=[r])
    
    if ('success' in ret_json and not ret_json['success']) or (len(ret_json.get('error', {}).get('messages', {})) > 0):
        ret.status_code = 400
        app.logger.debug(ret_json)
    else:
        ret.status_code = 200

    return ret

def add_browse_categories(item_json, browse_categories):
    """Add browse categories to the ScienceBase Item JSON
    :param item_json: ScienceBase Item JSON
    :param browse_categories: Browse categories to add
    :return: Updated ScienceBase Item JSON
    """
    app.logger.debug('add_browse_categories')

    if 'browseCategories' in item_json:
        for category in browse_categories:
            if category not in item_json['browseCategories']:
                item_json['browseCategories'].append(category)
    else:
        item_json['browseCategories'] = browse_categories
    return item_json

def merge_items(original_item, new_item):
    """Merge original and new ScienceBase Item JSON
    :param original_item: Existing ScienceBase Item JSON
    :param new_item: Updated ScienceBase Item JSON
    :return: Merged ScienceBase Item JSON
    """
    app.logger.debug('merge_items')

    # Set the ScienceBase ID, in case it was found by alternate identifier
    new_item['id'] = original_item['id']
    new_item['parentId'] = original_item['parentId']
    
    # Delete the iso and json files, but keep other files    
    new_item['files'] = [sbfile for sbfile in original_item['files'] if sbfile['name'] not in [app.config['MDJSON_FILENAME'], app.config['ISO2_FILENAME']]] if 'files' in original_item else []
            
    # Merge facets
    if 'facets' in new_item and new_item['facets']:
        app.logger.debug("Merging facets")
        if 'facets' in original_item:           
            # Keep the original project and budget facets if they exist
            orig_project_facet = None
            orig_budget_facet = None
            if 'facets' in original_item:
                for facet in original_item['facets']:
                    if facet['className'] == 'gov.sciencebase.catalog.item.facet.ProjectFacet':
                        orig_project_facet = facet     
                    elif facet['className'] == 'gov.sciencebase.catalog.item.facet.BudgetFacet':
                        orig_budget_facet = facet
            new_facet_names = []            
            for facet in new_item['facets']:
                # Get the project status from the new project facet and update the original one with it  
                if facet['className'] == 'gov.sciencebase.catalog.item.facet.ProjectFacet':
                    if orig_project_facet:
                        if 'projectStatus' in facet:
                            orig_project_facet['projectStatus'] = facet['projectStatus']
                    else:
                        orig_project_facet = facet  
                # Get the annual budget from the new budget facet and update the original one with it
                elif facet['className'] == 'gov.sciencebase.catalog.item.facet.BudgetFacet':
                    if orig_budget_facet:
                        if 'annualBudgets' in facet:
                            orig_budget_facet['annualBudgets'] = facet['annualBudgets']
                    else:
                        orig_budget_facet = facet
                    

                new_facet_names.append(facet['className'])     
                                 
            # Merge in any non-conflicting facets from the original item
            facets = [facet for facet in new_item['facets'] if not facet['className'].endswith('ProjectFacet') and not facet['className'].endswith('BudgetFacet')]
            if orig_project_facet:
                facets.append(orig_project_facet)
            if orig_budget_facet:
                facets.append(orig_budget_facet)
            facets.extend([facet for facet in original_item['facets'] if facet['className'] not in new_facet_names])
            new_item['facets'] = facets
        app.logger.debug("finished merging facets")
    elif 'facets' in original_item:
        app.logger.debug("No new facets, bringing in existing facets")
        new_item['facets'] = original_item['facets']

    # Merge tags
    if 'tags' in new_item and new_item['tags'] and 'tags' in original_item:
        new_item['tags'].extend([x for x in original_item['tags'] if x not in new_item['tags']])
    elif 'tags' in original_item:
        app.logger.debug("No new tags, bringing in existing tags")
        new_item['tags'] = original_item['tags'] 

    # Merge identifiers
    if 'identifiers' in new_item and new_item['identifiers'] and 'identifiers' in original_item:
        new_item['identifiers'].extend([x for x in original_item['identifiers'] if 'type' in x and x['type'] == COPY_SBID])
    elif 'identifiers' in original_item:
        new_item['identifiers'] = original_item['identifiers']

    # Remove duplicate identifiers:
    if 'identifiers' in new_item:
        ids = []
        for identifier in new_item['identifiers']:
            if identifier not in ids:
                ids.append(identifier)
        new_item['identifiers'] = ids
    
    return new_item

def create_associated_links(sb_item_id, md_json, base_folder_id):
    """Create associated Item Links
    :param sb_item_id: The ScienceBase ID of the item to link from
    :param md_json: mdJSON containing association information
    :param base_folder_id: Items must exist under the given folder
    """
    app.logger.debug("create_associated_links")
    errors = []
    # Create any required item links for item
    if 'associatedResource' in md_json.get('metadata', {}):
        for associated_resource in md_json['metadata']['associatedResource']:            
            if 'associationType' in associated_resource:
                app.logger.debug(associated_resource['associationType'])
                associated_resource_ids = get_resource_identifiers(associated_resource)
                if associated_resource_ids:
                    app.logger.debug("Creating link to %s" % (associated_resource_ids))
                    try:
                        association_type = associated_resource['associationType']
                        resource_type = get_resource_type(md_json)
                        create_item_link(association_type, resource_type, sb_item_id, associated_resource_ids, base_folder_id)
                    except Exception as e:
                        msg = "Unable to create %s relationship between %s and %s" % (associated_resource['associationType'], sb_item_id, str(associated_resource_ids))
                        errors.append(msg)
                        app.logger.error(msg)
                        app.logger.error(u"error: {0}".format(e).encode('ascii','ignore').decode('ascii'))
    return errors

def get_resource_type(md_json):
    """Get resource type from mdJSON
    :param md_json: mdJSON
    :return: Resource type
    """
    app.logger.debug('get_resource_type')
    ret = PRODUCT_RESOURCE_TYPE
    if md_json and 'resourceType' in md_json.get('metadata', {}).get('resourceInfo', {}):
        for resource_type in md_json['metadata']['resourceInfo']['resourceType']:
            if 'type' in resource_type and resource_type['type'] in RESOURCE_TYPES:
                ret = resource_type['type']
                break      
    return ret

def create_item_link(association_type, resource_type, parent_item_id, child_item_ids, base_folder_id):
    """Create an item link
    :param association_type: Type of association
    :param resource_type: Resource type
    :param parent_item_id: Parent item ID
    :param child_item_ids: List of identifiers by which to find the child item
    :param base_folder_id: Folder under which to look for the child item
    :return: ScienceBase ItemLink JSON
    """
    app.logger.debug('create_item_link %s %s:%s' % (association_type, parent_item_id, str(child_item_ids)))
    ret = None
    global _item_link_types
    sb = get_sb_session(request)

    # First, find the child
    search_item = {'identifiers': child_item_ids}
    for identifier in child_item_ids:
        if ('scheme' in identifier and identifier['scheme'] in SB_IDENTIFIERS) or ('type' in identifier and identifier['type'] in SB_IDENTIFIERS):
            search_item['id'] = identifier['key']
            break
    child_items = find_sb_items(search_item, base_folder_id)
    child_item_id = None
    if len(child_items) > 0:
        child_item_id = child_items[0]['id']
    else:
        # Can't find the related item, no need to continue
        app.logger.info("Child not found %s" % (str(child_item_ids)))
        return ret

    if not _item_link_types:
        # Load the known ItemLink types from vocab. This only needs to be done once.
        _item_link_types = {}
        for item_link_type in sb.get_item_link_types():
            _item_link_types[item_link_type['name']] = item_link_type['id']

    item_link_type_id = None
    reverse = False
    if association_type == PRODUCT_RESOURCE_TYPE:
        item_link_type_id = _item_link_types['productOf']
        reverse = True
    elif association_type == 'parentProject':
        # If this item is a project, it is a sub-project of the parent project
        # Otherwise it is a product of the parent project
        if PROJECT_RESOURCE_TYPE in resource_type:
            item_link_type_id = _item_link_types['subprojectOf']            
        else:
            item_link_type_id = _item_link_types['productOf']
        reverse = False
    elif association_type == 'subProject':
        item_link_type_id = _item_link_types['subprojectOf']
        reverse = True
    elif association_type == 'alternate':
        item_link_type_id = _item_link_types['alternate']
        reverse = False
    elif association_type == 'crossReference':
        item_link_type_id = _item_link_types['related']
        reverse = False

    if item_link_type_id and not has_link(parent_item_id, child_item_id, item_link_type_id, reverse):
        app.logger.debug('Create item link between %s and %s' % (parent_item_id, child_item_id))
        ret = sb.create_item_link(parent_item_id, child_item_id, item_link_type_id, reverse)
    return ret

def has_link(parent_item_id, child_item_id, item_link_type_id, reverse):
    """Return whether a link exists between the given items
    :param parent_item_id: Parent Item ID
    :param child_item_id: Child Item ID
    :param item_link_type_id: ID of the link type
    :param reverse: Whether the relationship is a reverse relationship
    :return: True if the link exists, otherwise False
    """
    app.logger.debug("has_link %s %s %s %s" % (parent_item_id, child_item_id, item_link_type_id, reverse))
    ret = False
    item_id = parent_item_id
    related_item_id = child_item_id
    if reverse:
        item_id = child_item_id
        related_item_id = parent_item_id

    existing_links = get_sb_session(request).get_item_links(item_id)
    for l in existing_links:
        if l['itemLinkTypeId'] == item_link_type_id and l['itemId'] == item_id and l['relatedItemId'] == related_item_id:
            ret = True
            break
    return ret

def find_sb_items(sb_json, base_folder_id):
    """ Find item by a list of identifiers
    :param sb_json: ScienceBase Item JSON
    :param base_folder_id: ID of the folder under which to search
    """
    app.logger.debug("find_sb_items")
    ret = []

    if 'id' in sb_json and sb_json['id']:
        # Verify the item is in the community
        if is_ancestor(sb_json['id'], base_folder_id):
            ret = [sb_json]
            app.logger.debug("Found by ScienceBase ID " + sb_json['id'])
        else:
            # For testing with copied communities
            items = find_items_by_identifier(COPY_SBID, sb_json['id'], base_folder_id)
            if len(items) > 0:
                ret = items

    # If it wasn't found by ID in the community, search for it by alternate identifier    
    if len(ret) == 0:
        for id_type, id_key in get_identifiers(sb_json).items():
            if id_key:
                app.logger.debug("Looking by identifier %s: %s" % (id_type, id_key))
                items = find_items_by_identifier(id_type, id_key, base_folder_id)
                if len(items) > 0:
                    ret = items
                    break
    return ret

def get_identifiers(sb_json):
    """Obtain the LCC identifiers for the record
    :param sb_json:
    :param handled_id_types:
    :return: Map of identifiers
    """
    app.logger.debug("get_identifiers")  
    ret = {}

    if sb_json and 'identifiers' in sb_json:
        for identifier in sb_json['identifiers']:
            id_type = None
            if 'scheme' in identifier and is_lcc_identifier(identifier['scheme']):
                id_type = identifier['scheme']
            elif 'type' in identifier and is_lcc_identifier(identifier['type']):
                id_type = identifier['type']
            if id_type:
                ret[id_type] = identifier['key']
    return ret

def is_lcc_identifier(type_or_scheme):
    ret = False
    if type_or_scheme in LCC_IDENTIFIERS:
        ret = True
    else:
        id_regex = re.compile(r"^(lcc:.*)|(.*?uuid.*)$")
        ret = id_regex.fullmatch(type_or_scheme) is not None
    return ret

def find_items_by_identifier(id_type, id_key, community_id):
    """Find ScienceBase Items by alternate identifier
    :param id_type: Type of ID
    :param id_key: Value of ID
    :param community_id: Folder under which to search
    :return: ScienceBase Items JSON
    """
    app.logger.debug("find_items_by_identifier")
    ret = []
    query = {
        'q':'', 
        'ancestors': community_id, 
    }
    if id_type in SB_IDENTIFIERS:
        query['lq'] = "id:%s" % (id_key)
    else:
        query['itemIdentifier'] = "{type:'%s',key:'%s'}" % (id_type, id_key)
    response = get_sb_session(request).find_items(query)
    if 'total' in response and response['total'] > 0:
        ret = response['items']
        app.logger.debug("Found by identifier %s: %s" % (id_type, id_key))
    return ret

def is_ancestor(item_id, folder_id):
    """Return whether the given Item is under the given Folder
    :param item_id: Item ID
    :param folder_id: Folder ID
    :return: Whether the Item is under the Folder
    """
    app.logger.debug("is_ancestor")
    ret = False
    try:
        item = get_sb_session(request).get_item(item_id, {'fields':ITEM_FIELDS})     
        ret = folder_id in item['ancestors']
    except:
        # Either it does not exist in ScienceBase or we don't have access
        ret = False
    app.logger.debug("is_ancestor %s %s %s" % (item_id, folder_id, str(ret)))
    return ret

def get_delete_ids(sb, item_id, delete_self):
    """Get list of Item IDs to delete in order to delete the given Item
    :param sb: sciencebasepy session
    :param item_id: Item ID
    :param delete_self: True to include the Item in the list, False to only include children
    """
    app.logger.debug('get_delete_ids')
    items_to_delete = []
    for child_id in sb.get_child_ids(item_id):
        items_to_delete.extend(get_delete_ids(sb, child_id, True))
    if delete_self:
        items_to_delete.append(item_id)
    return items_to_delete

def delete_item(item_id, browseCategory = None):
    """Delete the Item
    :param item_id: Item ID
    :param browseCategory: Browse category. Only delete if of specified type
    :return: ScienceBase Delete JSON
    """
    app.logger.debug('delete_item')
    ret = None
    
    sb = get_sb_session(request)
    item = sb.get_item(item_id, params={'fields':'ancestors,browseCategories'})
    if app.config['LC_MAP_ID'] not in item['ancestors']:
        ret = {'error': 'Item %s not in LC Map community' % item_id}
    elif browseCategory is not None and ('browseCategories' not in item or browseCategory not in item['browseCategories']):
        ret = {'error': 'Item %s not correct type, %s browse category not found' % (item_id, browseCategory)}
    else:
        delete_ids = get_delete_ids(sb, item_id, True)
        if sb.delete_items(delete_ids):
            ret = {'deleted': delete_ids}
        else:
            ret = {'error': 'Unable to delete %s' % item_id}
    return ret


def geojson_to_sb_extent(md_json):
    """Convert geojson in mdJSON to sbJSON extent JSON
    :param md_json: mdJSON
    :return: ScienceBase extent JSON
    """
    app.logger.debug('geojson_to_sb_extent')
    features = []
    if 'metadata' in md_json and 'resourceInfo' in md_json['metadata'] and 'extent' in md_json['metadata']['resourceInfo']:
        for extent in md_json['metadata']['resourceInfo']['extent']:
            if 'geographicExtent' in extent:
                for geographicExtent in extent['geographicExtent']:
                    if 'geographicElement' in geographicExtent:
                        for element in geographicExtent['geographicElement']:
                            features.extend(get_features(element))
    return features

def get_features(geographic_element):
    """Get geospatial features from geojson geographic element
    :param geographic_element: Geographic element
    :return: Features found in the geographic element
    """
    app.logger.debug('get_features')
    ret = []
    features = []
    if geographic_element['type'] == 'Feature':
        features.append(geographic_element)
    elif geographic_element['type'] == 'Polygon' or geographic_element['type'] == 'Point' or geographic_element['type'] == 'LineString':
        features.append({'type': 'Feature', 'properties': {}, 'geometry': geographic_element})
    elif geographic_element['type'] == 'FeatureCollection':
        features.extend(geographic_element['features'])
    for extent in features:
        if 'id' in extent:
            extent['properties']['name'] = extent['id']
            del(extent['id'])
        if extent['geometry']['type'] != 'GeometryCollection':
            ret.append(extent)
    return ret
