from flask import Blueprint, jsonify, request, make_response, abort, url_for
import pymongo
from bson.objectid import ObjectId
#from bson.json_util import dumps
from werkzeug.utils import secure_filename
import rosbag
import yaml
import json
import datetime
import os
import gridfs
from gridfs.errors import NoFile
import uuid
from pprint import pprint
import isodate as iso

# from bson import json_util
# import warnings
# warnings.filterwarnings('ignore')

mod = Blueprint('api', __name__)

DB = 'rosbagdb'
if os.environ.get('MONGO_CONNECTION_STRING') is not None:
    MONGO_CONNECTION_STRING = os.environ.get('MONGO_CONNECTION_STRING')
else:
    USER = os.environ.get('MONGO_USER')
    PASSWD = os.environ.get('MONGO_PASSWORD')
    SERVER = os.environ.get('MONGO_SERVER')
    MONGO_CONNECTION_STRING = "mongodb+srv://"+USER+":"+PASSWD+"@"+SERVER+"/"+DB+"?retryWrites=true&w=majority"

MONGO_DB = pymongo.MongoClient(MONGO_CONNECTION_STRING)[DB]
FS = gridfs.GridFS(MONGO_DB)

print('run with mongo_connection_string: '+MONGO_CONNECTION_STRING)

@mod.route('/test')
def test():
    return jsonify({'status': 'OK'})


####################################################################################

ALLOWED_EXTENSIONS = {'bin', 'bag', 'gif'}

KEY_TO_SKIP = ['message_definition',
               'md5sum',
               'type',
               'tcp_nodelay',
               'latching',
               'persistent',
               'error',
               'topic'
              ]

class MongoJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime.datetime, datetime.date)):
            return iso.datetime_isoformat(o)
        if isinstance(o, ObjectId):
            return str(o)
        else:
            return super().default(o)

mod.json_encoder = MongoJSONEncoder


class MongoJSONDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        self.orig_obj_hook = kwargs.pop("object_hook", None)
        super(MongoJSONDecoder, self).__init__(*args,object_hook=self.object_hook, **kwargs)

    def object_hook(self, obj):
        for (key, value) in obj.items():
            try:
                obj[key] = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
            except:
                pass
        
        if (self.orig_obj_hook):  # Do we have another hook to call?
            return self.orig_obj_hook(dct)  # Yes: then do it
        return obj


mod.json_decoder = MongoJSONDecoder

def date_converter(o):
    if isinstance(o, datetime.datetime):
            return o.__str__()

#########################################################################################

def process_rosbag(file_path):
    with rosbag.Bag(file_path, 'r') as bag:
        info_dict = yaml.load(bag._get_yaml_info())
        info_dict['start'] = datetime.datetime.fromtimestamp(info_dict['start'])
        info_dict['end'] = datetime.datetime.fromtimestamp(info_dict['end'])
        con_headers = {}
        for topic, msg, t, con in bag.read_messages(return_connection_header=True):
            if con:
                for key in con:
                    if key not in KEY_TO_SKIP:
                        if topic not in con_headers:
                            con_headers[topic] = {}
                        if key not in con_headers[topic]:
                            con_headers[topic][key] = set()
                        con_headers[topic][key].add(con[key])
        # convert sets to lists
        for t in con_headers:
            for k in con_headers[t]:
                con_headers[t][k] = list(con_headers[t][k])
        for el in info_dict['topics']:
            el['header_data'] = con_headers[el['topic']]

        print json.dumps(info_dict,default = date_converter,sort_keys=True, indent=4)
    return info_dict


def send_to_mongo(file_desc, file_path):
    try:
        fs = FS
        _filename = str(uuid.uuid4())+'.bag'
        print 'sending to mongo'
        data =  open(file_path, 'rb')
        #print type(data)
        iid = fs.put(data, filename=_filename, contentType='application/octet-stream')
        print('send to GridFS done', iid)

        file_desc['file_name_iid'] = _filename
        rid = MONGO_DB.rosbagfiles.insert_one(file_desc).inserted_id

    except Exception as e:
        print("send_to_mongo ERROR: ", e)
        return -1
    return str(rid)

###################################################################################

@mod.route('/getfile/<filename>')
def getfile(filename):
    """
    """
    try:
        if filename is not None:
            f = FS.get_last_version(filename)

            response = make_response(f.read())
            response.mimetype = f.content_type
            return response

    except Exception as e:
        print("getfile ERROR: ",e)
        abort(404)


@mod.route('/files/<oid>')
def serve_gridfs_file(oid):
    try:
        file = FS.get(ObjectId(oid))
        response = make_response(file.read())
        response.mimetype = file.content_type
        return response
    except Exception as e:
        print(e)
        abort(404)


@mod.route('/files')
def list_gridfs_files():
    files = [FS.get_last_version(file) for file in FS.list()]
    file_list = "\n".join(['<li><a href="%s">%s</a></li>' % \
                            (url_for('api.serve_gridfs_file', oid=str(file._id)), file.name) \
                            for file in files])
    return '''
    <!DOCTYPE html>
    <html>
    <head>
    <title>Files</title>
    </head>
    <body>
    <h1>Files</h1>
    <ul>
    %s
    </ul>
    </body>
    </html>
    ''' % (file_list)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@mod.route('/file-upload', methods=['POST'])
def upload_file():
    # check if the post request has the file part
    if 'file' not in request.files:
        resp = jsonify({'message': 'No file part in the request'})
        resp.status_code = 400
        return resp
    file = request.files['file']
    if file.filename == '':
        resp = jsonify({'message': 'No file selected for uploading'})
        resp.status_code = 400
        return resp
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        #file_path = '/tmp/' + filename
        file_path = filename
        file.save(file_path)
        # file processing i.e. header read, storing to mongo
        data_to_mongo = process_rosbag(file_path)
        # send data to mongo
        doc_id = send_to_mongo(data_to_mongo,file_path)
        # Remove uploaded file
        if os.path.exists(file_path):
            os.remove(file_path)
        else:
            print("The file does not exist")
        #print('DONE')
        resp = jsonify({'message': 'File successfully uploaded','_id': doc_id})
        resp.status_code = 201
        return resp
    else:
        resp = jsonify({'message': 'Allowed file types are *.bag or *.bin'})
        resp.status_code = 400
        return resp


@mod.route('/rosbagfiles', methods=['POST'])
def api_post_rosbagfiles():
    """
    API for rosbagfiles
    return: JSON response date from database
    """
    response = {}
    if not request.content_type == 'application/json':
        response['status'] = 'BAD_REQUEST'
        return jsonify(response), 400

    # get, parse and validate request content
    jo = request.get_json()
    #print(type(jo))
    #print(jo)

    _filter = {}
    if 'filter' in jo:
        _filter = jo['filter']

    _skip = 0
    _limit = 20
    #_projection = {'_id':0,'file_name_iid':1,'path':1,'start':1} 
    _projection = None

    if 'skip' in jo:
        _skip = int(jo['skip'])
    if 'limit' in jo:
        _limit = int(jo['limit'])
    if 'projection' in jo:
        _projection = jo['projection']


    results = []
    #print(_filter)
    for x in MONGO_DB.rosbagfiles.find(_filter, _projection).skip(_skip).limit(_limit):
        #pprint(x)
        results.append(x)

    return jsonify(results)
