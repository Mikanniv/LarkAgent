"""Local authoring/QA client; requires the project-local PSD2Live headless server."""
import json, sys, importlib.util
from pathlib import Path

root=Path(__file__).resolve().parents[3]
tools=root/'desktop/.local/tools'
spec=importlib.util.spec_from_file_location('psd2live_proxy',tools/'psd2live-sparse/mcp_proxy.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)
token=next(line[6:].strip() for line in (tools/'rig-server.log').read_text().splitlines() if line.startswith('token '))
op=sys.argv[1];request=json.loads(sys.argv[2]) if len(sys.argv)>2 else {}
with proxy.Client(endpoint='http://127.0.0.1:23871/mcp',token=token,timeout=90) as client:
    if '--edit' in sys.argv:request.setdefault('state',client.state())
    data,images=client.call(op,request)
    out=root/'art/live2d/human-v1/qa';out.mkdir(exist_ok=True)
    label=sys.argv[sys.argv.index('--label')+1] if '--label' in sys.argv else op
    (out/(label+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    for i,image in enumerate(images):(out/(label+f'-{i}.png')).write_bytes(image)
    print(json.dumps(data,ensure_ascii=False))
    if images:print(json.dumps({'images':[str(out/(label+f'-{i}.png')) for i in range(len(images))]}))
