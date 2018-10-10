from sanic import Sanic
from sanic.response import json as json_response
import io, json, asyncio, os, itertools, re
from websockets.exceptions import ConnectionClosed
import xmlrpc.client
import yaml
from sanic_cors import CORS

config = yaml.load(io.open('config.yml', 'r'))
supervisor = xmlrpc.client.ServerProxy(config['supervisor']['url']).supervisor
app = Sanic()
CORS(app)

@app.websocket('/logs/<name>/<log_name>')
async def feed(request, ws, name, log_name):
  # Filter query
  query = request.args.get('filter')
  log_path = get_log_path(name, log_name)
  with io.open(log_path, 'rb') as log_file:
    last_pos = log_file.seek(0, io.SEEK_END)
    lines = tail(log_file, 100)
    if query:
      lines = list_filter(lines, query)
    await ws.send(json.dumps(lines))
    log_file.seek(last_pos)
    # Follow
    while True:
      try:
        lines = byte_to_str(log_file.readlines())
        if len(lines) > 0:
          if query:
            lines = list_filter(lines, query)
          await ws.send(json.dumps(lines))
        # Add delay
        await asyncio.sleep(1)
      except (ConnectionClosed):
        print('closed')
        log_file.close()
        break

@app.get('/programs')
async def programs(request):
  process = supervisor.getAllProcessInfo()
  return json_response([
    {
      'name': p['name'],
      'statename': p['statename'],
      'description': p['description'],
      'logs': get_log(p['name'])
    } for p in process]
  )

@app.get('/programs/<name>')
async def program_detail(request, name):
  process = supervisor.getProcessInfo(name)
  return json_response({
    'name': process['name'],
    'statename': process['statename'],
    'description': process['description'],
    'logs': get_log(process['name'])
  })

def get_log(name):
  return ['stderr', 'stdout'] + get_custom_log(name)

def get_custom_log(name):
  try:
    return list(config['programs'][name]['logs'].keys())
  except Exception as e:
    return []

def get_log_path(name, log_name):
  program = supervisor.getProcessInfo(name)
  if log_name == 'stdout':
    return program['stdout_logfile']
  if log_name == 'stderr':
    return program['stderr_logfile']
  return get_custom_log_path(name, log_name)

def get_custom_log_path(name, log_name):
  try:
    return config['programs'][name]['logs'][log_name]
  except:
    return None

def tail(file, line_count):
  BUFFER_SIZE = 1024
  pos = -BUFFER_SIZE
  offset = 0
  result_lines = []
  result_line_count = 0
  while result_line_count < line_count:
    file.seek(pos, io.SEEK_END)
    text = file.read(BUFFER_SIZE + offset)
    try:
      offset = text.index(b'\n')
    except ValueError:
      offset = len(text)
      pos = pos - BUFFER_SIZE
      continue
    lines = text.splitlines()[1:]
    line_to_add = line_count - len(result_lines)
    if len(lines) >= line_to_add:
      result_lines.append(lines[-line_to_add:len(lines)])
    else:
      result_lines.append(lines)
    result_line_count+=len(lines)
    pos = pos - BUFFER_SIZE
  
  result_lines.reverse()
  flat_list = list(itertools.chain.from_iterable(result_lines))
  return byte_to_str(flat_list)

def byte_to_str(l):
  return [i.decode('utf-8') for i in l]

def list_filter(str_list, filter):
  return [s for s in str_list if re.search(filter, s, re.IGNORECASE)]

if __name__ == '__main__':
  app.run(host=config['bind'], port=config['port'])
  