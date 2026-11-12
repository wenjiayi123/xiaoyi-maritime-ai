"""Standard-library equipment tool. Uses no sockets, model server or pickle."""
import argparse,hashlib,json,math,sys
from pathlib import Path
BASE=Path(__file__).resolve().parent
PIN="a9efa73cf65cd51a0076e6af40f7136813e280f7623f5ce1b2cbe309c66fa47a"
def load(path,pin):
    b=path.read_bytes()
    if hashlib.sha256(b).hexdigest()!=pin:raise ValueError("研究模型或回执校验不符")
    return json.loads(b)
def predict(model,req,h):
    if type(h)!=int or h not in (10,30):raise ValueError("仅支持 10 或 30 帧")
    if set(req)!={"coordinate_system","sequence","observations"} or req["coordinate_system"]!="camera_bbox_center_px":raise ValueError("需要图像平面的吊具框中心坐标")
    if not isinstance(req["sequence"],str) or not req["sequence"].strip():raise ValueError("缺少同一镜头作业段标识")
    rows=req["observations"]
    if not isinstance(rows,list) or len(rows)!=11:raise ValueError("需要同一作业段最近连续 11 帧")
    for i,r in enumerate(rows):
        if not isinstance(r,dict) or set(r)!={"frame","x","y"} or type(r["frame"])!=int or r["frame"]<0 or (i and r["frame"]!=rows[i-1]["frame"]+1):raise ValueError("帧号必须连续且有序")
        if not all(type(r[k]) in (int,float) and math.isfinite(r[k]) for k in ("x","y")):raise ValueError("坐标必须为有限像素值")
    last=rows[-1];v=model["pose"][str(h)];method=v["choice"]
    x=[last[k]-rows[-1-back][k] for back in (1,5,10) for k in ("x","y")]
    assert method=="ridge"
    point=[last[k]+sum(z*w[j] for z,w in zip(x,v["weights"])) for j,k in enumerate(("x","y"))]
    if not all(map(math.isfinite,point)):raise ValueError("坐标超出数值范围")
    return {"sequence":req["sequence"],"origin":last["frame"],"target":last["frame"]+h,"center_px":point,"model":method,"unit":"px","horizon_frames":h,"mode":"offline_research","physical_control":False}
def main():
    argv=sys.argv[1:];argv=argv[1:] if argv[:1]==["equipment"] else argv
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="action",required=True)
    pose=sub.add_parser("pose");pose.add_argument("--input",required=True,type=Path);pose.add_argument("--horizon",type=int,choices=(10,30),required=True)
    sub.add_parser("report")
    a=p.parse_args(argv)
    if a.action=="pose":out=predict(load(BASE/"frozen.json",PIN),json.loads(a.input.read_bytes()),a.horizon)
    else:
        from evidence_pin import EVIDENCE_SHA
        out=load(BASE/"evidence.json",EVIDENCE_SHA)
    print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=="__main__":
    try:main()
    except (ValueError,OSError,TypeError,KeyError) as e:print(str(e),file=sys.stderr);sys.exit(2)
