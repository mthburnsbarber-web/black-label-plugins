"""Small dependency-free MCP stdio transport shared by local plugins.

All payloads are newline-delimited JSON-RPC; stdout contains protocol only.
"""
import json
import sys

VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')


def serve(name, tools, dispatch, instructions):
    def send(value):
        print(json.dumps(value, ensure_ascii=False), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        req = None
        try:
            if len(line) > 2_000_000:
                raise ValueError('request exceeds 2MB')
            req = json.loads(line)
            if not isinstance(req, dict) or req.get('jsonrpc') != '2.0':
                raise ValueError('expected JSON-RPC 2.0 object')
        except (ValueError, TypeError):
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON-RPC request'}})
            continue
        if 'id' not in req:
            continue
        ident, method, params = req['id'], req.get('method'), req.get('params', {})
        try:
            if not isinstance(params, dict):
                raise ValueError('params must be an object')
            if method == 'initialize':
                version = params.get('protocolVersion')
                result = {'protocolVersion': version if version in VERSIONS else VERSIONS[0],
                          'capabilities': {'tools': {'listChanged': False}},
                          'serverInfo': {'name': name, 'version': '1.0.2'}, 'instructions': instructions}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': tools}
            elif method == 'tools/call':
                tool = next((t for t in tools if t['name'] == params.get('name')), None)
                if not tool:
                    raise ValueError('unknown tool')
                args = params.get('arguments', {})
                validate(args, tool['inputSchema'])
                value = dispatch(tool['name'], args)
                if isinstance(value, dict) and '_mcp_content' in value:
                    result = {'content': value['_mcp_content']}
                else:
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
            else:
                send({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'Method not found'}})
                continue
            send({'jsonrpc': '2.0', 'id': ident, 'result': result})
        except Exception as exc:
            # Handlers never put credential inputs in exception messages.
            if method == 'tools/call':
                send({'jsonrpc': '2.0', 'id': ident, 'result': {'isError': True, 'content': [
                    {'type': 'text', 'text': str(exc)[:1500]}]}})
            else:
                send({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32602, 'message': str(exc)[:300]}})


def validate(value, schema, path='arguments'):
    types = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'integer': int, 'number': (int, float)}
    expected = schema.get('type')
    if expected in types and (not isinstance(value, types[expected]) or expected in ('integer', 'number') and isinstance(value, bool)):
        raise ValueError(path + ' has incorrect type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ' is not a supported value')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                raise ValueError(path + '.' + key + ' is required')
        for key, item in value.items():
            if key not in props and schema.get('additionalProperties') is False:
                raise ValueError(path + ' contains an unknown field')
            if key in props:
                validate(item, props[key], path + '.' + key)
    if isinstance(value, list):
        if len(value) > schema.get('maxItems', 1000):
            raise ValueError(path + ' contains too many items')
        for item in value:
            validate(item, schema.get('items', {}), path + '[]')
    if isinstance(value, str) and len(value) > schema.get('maxLength', 50000):
        raise ValueError(path + ' is too long')


def spec(name, description, properties=None, required=(), read=False):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties or {}, 'required': list(required), 'additionalProperties': False},
            'annotations': {'readOnlyHint': read, 'destructiveHint': False, 'openWorldHint': True}}


S = {'type': 'string'}
B = {'type': 'boolean'}
I = {'type': 'integer'}
