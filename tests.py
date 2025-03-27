import unittest
import getpass
import json
from sciencebasepy import SbSession
import time
import config.config as config

class MdPublisher(unittest.TestCase):
    """
    In config/config.py, set LC_MAP_ID to a test folder. Then run the service
    locally. Note: Test folder MUST be underneath the LC Map community. The
    service will not look outside of the LC Map community for items.
    """
    SESSION = None
    SB_SESSION = None
    MD_PUBLISHER_URL = "http://localhost:5000"
 
    @classmethod
    def setUpClass(self):
        super(MdPublisher, self).setUpClass()
        print("Environment: %s Folder: %s" % (config.SCIENCEBASE_ENV, config.LC_MAP_ID))
        TEST_USER = input("Username:  ")
        TEST_PASSWORD = getpass.getpass()
        self.SB_SESSION = SbSession(config.SCIENCEBASE_ENV).login(TEST_USER, TEST_PASSWORD)
        self.SESSION = self.SB_SESSION._session

    def test_geojson(self):
        md_json = {
            'data': {
                'parentid':'',
                'mdjson':{},
                'relationships':[]
            }
        }
        test_json = None
        with open('md_metadata.json', 'r') as test_json_file:
            test_json = json.load(test_json_file)
        md_json['data']['mdjson'] = test_json
        md_json['data']['parentid'] = config.LC_MAP_ID

        response = self.SESSION.post(self.MD_PUBLISHER_URL + "/product", json=md_json)
        self.assertIsNotNone(response.text)
        self.assertEqual(200, response.status_code)

    def test_create_product(self):
        md_json = None
        with open('test.json', 'r') as test_json_file:
            md_json = json.load(test_json_file)
        md_json['data']['parentid'] = config.LC_MAP_ID

        for product_id in [
            {'type': 'gov.sciencbase.catalog', 'scheme': 'gov.sciencbase.catalog', 'key': '50f47cf8e4b0f1f5e1b68acf'},
            {'type': 'gov.sciencbase.catalog', 'scheme': 'gov.sciencbase.catalog', 'key': '57c7111ae4b0f2f0cebed08f'}]:
            if not self.id_exists(product_id):
                self.SB_SESSION.create_item({'parentId': config.LC_MAP_ID, 'title': 'Product', 'identifiers': [product_id]})

        response = self.SESSION.post(self.MD_PUBLISHER_URL + "/product", json=md_json)
        self.assertIsNotNone(response.text)
        self.assertEqual(200, response.status_code)

    def id_exists(self, id):
        items = self.SB_SESSION.find_items({'ancestors': config.LC_MAP_ID, 'filter':'itemIdentifier=' + str(id)})
        return items['total'] > 0

    def test_create_project(self):
        md_json = None
        with open('test.json', 'r') as test_json_file:
            md_json = json.load(test_json_file)
        md_json['data']['parentid'] = config.LC_MAP_ID

        for product_id in [
            {'type': 'gov.sciencbase.catalog', 'scheme': 'gov.sciencbase.catalog', 'key': '50f47cf8e4b0f1f5e1b68acf'},
            {'type': 'gov.sciencbase.catalog', 'scheme': 'gov.sciencbase.catalog', 'key': '57c7111ae4b0f2f0cebed08f'}]:
            if not self.id_exists(product_id):
                self.SB_SESSION.create_item({'parentId': config.LC_MAP_ID, 'title': 'Product', 'identifiers': [product_id]})

        response = self.SESSION.post(self.MD_PUBLISHER_URL + "/project", json=md_json)
        self.assertIsNotNone(response.text)
        self.assertEqual(200, response.status_code)

    def test_put_not_exist(self):
        md_json = None
        with open('association.json', 'r') as test_json_file:
            md_json = json.load(test_json_file)
        response = self.SESSION.put(self.MD_PUBLISHER_URL + "/product/1b2c3d4e5f6a7b8c9d0e1f2a", json=md_json)
        self.assertEqual(400, response.status_code)
        self.assertIn('error', response.text)


    def test_bad_mdjson(self):
        md_json = {
            'data': {
                'parentid':'',
                'mdjson':{},
                'relationships':[]
            }
        }
        response = self.SESSION.post(self.MD_PUBLISHER_URL + "/product", json=md_json)
        self.assertEqual(400, response.status_code)
        self.assertIn('error', response.text)

    def test_delete_product(self):
        item = self.SB_SESSION.create_item({"title": "Delete Me", "parentId": config.LC_MAP_ID})
        self.assertIn('id', item)
        response = self.SESSION.delete(self.MD_PUBLISHER_URL + "/product/" + item['id'])
        self.assertIn(item['id'], response.json().get('deleted', {}))

    def test_association(self):
        with open('association.json', 'r') as test_json_file:
            md_json = json.load(test_json_file)

        project = self.SB_SESSION.create_item({"title": "Project", "parentId": config.LC_MAP_ID})
        md_json['data']['parentid'] = project['parentId']
        md_json['data']['mdjson']['metadata']['metadataInfo']['metadataIdentifier']['identifier'] = project['id']
        

        md_json['data']['mdjson']['metadata']['metadataInfo']['parentMetadata']['identifier'][0]['identifier'] = project['parentId']

        product = self.SB_SESSION.create_item({
            "title": "Product", 
            "parentId": project['id']
        })
        md_json['data']['mdjson']['metadata']['associatedResource'][0]['resourceCitation']['identifier'][0]['identifier'] = product['id']

        response = self.SESSION.put(self.MD_PUBLISHER_URL + "/project/" + project['id'], json=md_json)
        self.assertIsNotNone(response.text)
        self.assertEqual(200, response.status_code)

        links = self.SB_SESSION.get_item_links(project['id'])
        self.assertEqual(1, len(links))

    def test_facet_merge(self):
        sbitem = {
            "title":"Project","summary":"This is a test project for the mdEditor",
            "body":"This is a test project for the mdEditor",
            "citation":"2017-11-03(creation), 2017-11-03(lastUpdate), Project",
            "provenance":{"annotation":"generated using ADIwg mdTranslator 2.6.0","dateCreated":"2017-11-27T18:45:08Z","lastUpdated":"2017-12-05T15:09:12Z","lastUpdatedBy":"jllong@usgs.gov","createdBy":"jllong@usgs.gov"},
            "contacts":[
                {"name":"Dell Long","type":"Point of Contact","contactType":"person","organization":{},"primaryLocation":{"streetAddress":{},"mailAddress":{}}},
                {"name":"Dell Long","type":"Author","contactType":"person","organization":{},"primaryLocation":{"streetAddress":{},"mailAddress":{}}}],
            "browseCategories":["Data","Project"],
            "tags":[{"type":"Resource Type","name":"Project"},{"type":"Status","name":"accepted"}],
            "dates":[{"type":"creation","dateString":"2017-11-03 18:55:11","label":""},{"type":"lastUpdate","dateString":"2017-11-03 18:55:11","label":""},{"type":"Start","dateString":"2017-11-01 19:06:35","label":""}],
            "facets":[{"projectStatus":"Proposed","projectProducts":[],"parts":[{"type":"part1","value":"This is a part"},{"type":"part2","value":"This is another part"}],"className":"gov.sciencebase.catalog.item.facet.ProjectFacet","facetName":"Project"},
            {"parts":[{"type":"part1","value":"This is a part"},{"type":"part2","value":"This is another part"}],"totalFunds":0.0,"annualBudgets":[],"className":"gov.sciencebase.catalog.item.facet.BudgetFacet","facetName":"Budget"}],
        }
        sbitem['parentId'] = config.LC_MAP_ID
        sbitem = self.SB_SESSION.create_item(sbitem)

        md_json = {
            "schema": {"version": "2.0.0", "name": "mdJson"}, 
            "contact": [{"contactId": "ba577187-4089-4251-b54a-51f1e3568be9", "isOrganization": False, "name": "Dell Long"}], 
            "metadata": {
                "resourceInfo": {"status": ["accepted"], "pointOfContact": [{"party": [{"contactId": "ba577187-4089-4251-b54a-51f1e3568be9"}], "role": "author"}], 
                "resourceType": [{"type": "project", "name": "Test Project"}], 
                "abstract": "This is a test project for the mdEditor", 
                "citation": {"date": [{"date": "2017-11-03T18:55:11+00:00", "dateType": "creation"}, {"date": "2017-11-03T18:55:11+00:00", "dateType": "lastUpdate"}], "title": "Project"}, 
                "defaultResourceLocale": {"country": "USA", "characterSet": "UTF-8", "language": "eng"}, 
                "timePeriod": {"timeInterval": {"units": "year", "interval": 1}, "startDateTime": "2017-11-01T19:06:35.577Z"}}, 
                "metadataInfo": {
                    "metadataIdentifier": {"identifier": sbitem['id'], "namespace": "gov.sciencebase.catalog", "description": "USGS ScienceBase Identifier", "authority": {"date": [{"date": "2017-12-04T22:59:42.927Z", "dateType": "published", "description": "Published using mdEditor"}, {"date": "2017-12-04T23:01:06.792Z", "dateType": "published", "description": "Published using mdEditor"}], "title": "ScienceBase"}}, 
                    "parentMetadata": {"identifier": [{"identifier": sbitem['parentId'], "namespace": "gov.sciencebase.catalog", "description": "USGS ScienceBase Identifier", "authority": {"date": [{"date": "2017-12-04T23:01:06.792Z", "dateType": "published", "description": "Published using mdEditor"}], "title": "ScienceBase"}}], "title": "U.S. Geological Survey ScienceBase parent identifier"}, "defaultMetadataLocale": {"country": "USA", "characterSet": "UTF-8", "language": "eng"}, 
                    "metadataStatus": "accepted", "metadataContact": [{"party": [{"contactId": "ba577187-4089-4251-b54a-51f1e3568be9"}], "role": "pointOfContact"}]}, 
                    "associatedResource": [{"resourceType": [{"type": "report", "name": "Report"}], "associationType": "product", "resourceCitation": {"identifier": [{"identifier": "5a1c5d34e4b09fc93dd6438f", "namespace": "gov.sciencebase.catalog", "authority": {"title": "Product"}}], "title": "Product"}}],
                    "funding": [{"allocation": [{"currency": "USD", "amount": 1104}], "timePeriod": {"endDateTime": "2017-10-01T05:59:59.999Z", "startDateTime": "2016-10-01T06:00:00.000Z"}}]}
                    
        }
     
        response = self.SESSION.put(self.MD_PUBLISHER_URL + "/project/" + sbitem['id'], json={"data":{"parentid": sbitem['parentId'], "mdjson": md_json}})
        self.assertEqual(200, response.status_code)
        item = response.json()
        self.assertTrue('facets' in item)
        for facet in item['facets']:
            if facet['facetName'] in ["Project", "Budget"]:
                self.assertTrue('parts' in facet and len(facet['parts']) == 2)

if __name__ == '__main__':
    unittest.main()