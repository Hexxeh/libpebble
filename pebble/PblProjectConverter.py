import json
import os
import re
import shutil

from PblCommand import PblCommand
from PblProjectCreator import *

def read_c_code(c_file_path):

    C_SINGLELINE_COMMENT_PATTERN = '//.*'
    C_MULTILINE_COMMENT_PATTERN = '/\*.*\*/'

    with open(c_file_path, 'r') as f:
        c_code = f.read()

        c_code = re.sub(C_SINGLELINE_COMMENT_PATTERN, '', c_code)
        c_code = re.sub(C_MULTILINE_COMMENT_PATTERN, '', c_code)

        return c_code

def convert_c_uuid(c_uuid):

    C_UUID_BYTE_PATTERN = '0x([0-9A-Fa-f]{2})'
    C_UUID_PATTERN = '^{\s*' + '\s*,\s*'.join([C_UUID_BYTE_PATTERN] * 16) + '\s*}$'

    UUID_FORMAT = "{}{}{}{}-{}{}-{}{}-{}{}-{}{}{}{}{}{}"

    c_uuid = c_uuid.lower()
    if re.match(C_UUID_PATTERN, c_uuid):
        return UUID_FORMAT.format(*re.findall(C_UUID_BYTE_PATTERN, c_uuid))
    else:
        return c_uuid

def extract_c_macros_from_code(c_code, macros={}):

    C_IDENTIFIER_PATTERN = '[A-Za-z_]\w*'
    C_DEFINE_PATTERN = '#define\s+('+C_IDENTIFIER_PATTERN+')\s+\(*(.+)\)*\s*'

    for m in re.finditer(C_DEFINE_PATTERN, c_code):
        groups = m.groups()
        macros[groups[0]] = groups[1].strip()

def extract_c_macros_from_project(project_root, macros={}):
    src_path = os.path.join(project_root, 'src')
    for root, dirnames, filenames in os.walk(src_path):
        for f in filenames:
            file_path = os.path.join(root, f)
            extract_c_macros_from_code(read_c_code(file_path), macros)

    return macros

def convert_c_expr_dict(c_expr_dict, project_root):

    C_STRING_PATTERN = '^"(.*)"$'

    macros = extract_c_macros_from_project(project_root)
    for k, v in c_expr_dict.iteritems():
        if v == None:
            continue

        # Expand C macros
        if v in macros:
            v = macros[v]

        # Format C strings
        m = re.match(C_STRING_PATTERN, v)
        if m:
            v = m.groups()[0].decode('string-escape')

        c_expr_dict[k] = v

    return c_expr_dict

def find_pbl_app_info(project_root):

    C_LITERAL_PATTERN = '([^,]+|"[^"]*")'

    PBL_APP_INFO_PATTERN = (
            'PBL_APP_INFO(?:_SIMPLE)?\(\s*' +
            '\s*,\s*'.join([C_LITERAL_PATTERN] * 4) +
            '(?:\s*,\s*' + '\s*,\s*'.join([C_LITERAL_PATTERN] * 3) + ')?' +
            '\s*\)'
            )

    PBL_APP_INFO_FIELDS = [
            'uuid',
            'name',
            'company_name',
            'version_major',
            'version_minor',
            'menu_icon',
            'type'
            ]

    src_path = os.path.join(project_root, 'src')
    for root, dirnames, filenames in os.walk(src_path):
        for f in filenames:
            file_path = os.path.join(root, f)
            m = re.search(PBL_APP_INFO_PATTERN, read_c_code(file_path))
            if m:
                return dict(zip(PBL_APP_INFO_FIELDS, m.groups()))

def extract_c_appinfo(project_root):

    appinfo_c_def = find_pbl_app_info(project_root)
    if not appinfo_c_def:
        raise Exception("Could not find usage of PBL_APP_INFO")

    appinfo_c_def = convert_c_expr_dict(appinfo_c_def, project_root)

    version_major = int(appinfo_c_def['version_major'] or '1', 0)
    version_minor = int(appinfo_c_def['version_minor'] or '0', 0)

    appinfo_json_def = {
        'uuid': convert_c_uuid(appinfo_c_def['uuid']),
        'short_name': appinfo_c_def['name'],
        'long_name': appinfo_c_def['name'],
        'company_name': appinfo_c_def['company_name'],
        'version_code': version_major,
        'version_label': '{}.{}.0'.format(version_major, version_minor),
        'menu_icon': appinfo_c_def['menu_icon'],
        'is_watchface': 'true' if appinfo_c_def['type'] == 'APP_INFO_WATCH_FACE' else 'false',
        'app_keys': '{}',
        'resources_media': '[]',
    }

    return appinfo_json_def

def load_app_keys(js_appinfo_path):
    with open(js_appinfo_path, "r") as f:
        try:
            app_keys = json.load(f)['app_keys']
        except:
            raise Exception("Failed to import app_keys from {} into new appinfo.json".format(js_appinfo_path))

        app_keys = json.dumps(app_keys, indent=2)
        return re.sub('\s*\n', '\n  ', app_keys)

def load_resources_map(resources_map_path, menu_icon_name=None):

    C_RESOURCE_PREFIX = 'RESOURCE_ID_'

    def convert_resources_media_item(item):
        if item['file'] == 'resource_map.json':
            return None
        else:
            item_name = item['defName']
            del item['defName']
            item['name'] = item_name

            if menu_icon_name and C_RESOURCE_PREFIX + item_name == menu_icon_name:
                item['menuIcon'] = True

            return item

    with open(resources_map_path, "r") as f:
        try:
            resources_media = json.load(f)['media']
        except:
            raise Exception("Failed to import {} into appinfo.json".format(resources_map_path))

        resources_media = filter(None, [convert_resources_media_item(item) for item in resources_media])
        resources_media = json.dumps(resources_media, indent=2)
        return re.sub('\s*\n', '\n    ', resources_media)

def generate_appinfo_from_old_project(project_root, js_appinfo_path=None, resources_media_path=None):
    appinfo_json_def = extract_c_appinfo(project_root)

    if js_appinfo_path and os.path.exists(js_appinfo_path):
        appinfo_json_def['app_keys'] = load_app_keys(js_appinfo_path)

    if resources_media_path and os.path.exists(resources_media_path):
        menu_icon_name = appinfo_json_def['menu_icon']
        appinfo_json_def['resources_media'] = load_resources_map(resources_media_path, menu_icon_name)

    with open(os.path.join(project_root, "appinfo.json"), "w") as f:
        f.write(FILE_DUMMY_APPINFO.substitute(**appinfo_json_def))

def convert_project():
    project_root = os.getcwd()

    js_appinfo_path = os.path.join(project_root, 'src/js/appinfo.json')

    resources_path = 'resources/src'
    resources_media_path = os.path.join(project_root, os.path.join(resources_path, 'resource_map.json'))

    generate_appinfo_from_old_project(
            project_root,
            js_appinfo_path=js_appinfo_path,
            resources_media_path=resources_media_path)

    links_to_remove = [
            'include',
            'lib',
            'pebble_app.ld',
            'tools',
            'waf',
            'wscript'
            ]

    for l in links_to_remove:
        if os.path.islink(l):
            os.unlink(l)

    if os.path.exists('.gitignore'):
        os.remove('.gitignore')

    if os.path.exists('.hgignore'):
        os.remove('.hgignore')

    with open("wscript", "w") as f:
        f.write(FILE_WSCRIPT)

    with open(".gitignore", "w") as f:
        f.write(FILE_GITIGNORE)

    if os.path.exists(js_appinfo_path):
        os.remove(js_appinfo_path)

    if os.path.exists(resources_media_path):
        os.remove(resources_media_path)

    if os.path.exists(resources_path):
        try:
            for f in os.listdir(resources_path):
                shutil.move(os.path.join(resources_path, f), os.path.join('resources', f))
            os.rmdir(resources_path)
        except:
            raise Exception("Could not move all files in {} up one level".format(resources_path))

class PblProjectConverter(PblCommand):
    name = 'convert-project'
    help = """convert an existing Pebble project to the current SDK.

Note: This will only convert the project, you'll still have to update your source to match the new APIs."""

    def run(self, args):
        try:
            check_project_directory()
            print "No conversion required"
        except OutdatedProjectException:
            convert_project()
            print "Project successfully converted!"

