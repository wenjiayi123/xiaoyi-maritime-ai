
const db=JSON.parse(document.getElementById("data").textContent),el=id=>document.getElementById(id),labels={hold:"保持原位",velocity1:"上一帧匀速",velocity5:"五帧匀速",velocity10:"十帧匀速",ridge:"训练模型"};
for(const s of Object.keys(db.result.pose["10"]))el("clip").add(new Option(s,s));
for(const [s,r] of Object.entries(db.result.health)){const a=r.all.thermal;el("health").insertRow().innerHTML=[s,a.tp,a.fp,a.fn,a.tn].map(x=>"<td>"+x+"</td>").join("")}
el("false").textContent=db.evidence.thermal["误报"].toLocaleString("en-US");
function show(reset){const s=el("clip").value,h=el("h").value,rows=db.rows.filter(r=>r.sequence===s&&String(r.horizon)===h),sl=el("step");sl.max=rows.length-1;if(reset)sl.value=0;
const row=rows[+sl.value],pts=[row.origin,row.target,row.predicted[row.selected],row.predicted.velocity10],n=pts.map(p=>p[0]),m=pts.map(p=>p[1]),cx=(Math.min(...n)+Math.max(...n))/2,cy=(Math.min(...m)+Math.max(...m))/2;
const scale=Math.min(510/Math.max(35,Math.max(...n)-Math.min(...n)),185/Math.max(35,Math.max(...m)-Math.min(...m)));
const [a,b,c,d]=pts.map(p=>[315+(p[0]-cx)*scale,140+(p[1]-cy)*scale]),line=(p,q,col,dash)=>'<line x1="'+p[0]+'" y1="'+p[1]+'" x2="'+q[0]+'" y2="'+q[1]+'" stroke="'+col+'" stroke-width="2" stroke-dasharray="'+dash+'"/>';
el("plot").innerHTML=line(a,b,"#005755","2 3")+line(a,c,"#a44e22","6 3")+line(a,d,"#586592","6 5")+'<circle cx="'+a[0]+'" cy="'+a[1]+'" r="4" fill="#263434"/><circle cx="'+b[0]+'" cy="'+b[1]+'" r="8" fill="none" stroke="#005755" stroke-width="3"/><path d="M '+c[0]+' '+(c[1]-6)+' l 6 6 -6 6 -6 -6 z" fill="#a44e22"/>'+line([d[0]-6,d[1]-6],[d[0]+6,d[1]+6],"#586592","")+line([d[0]+6,d[1]-6],[d[0]-6,d[1]+6],"#586592","");
const dist=p=>Math.hypot(p[0]-pts[1][0],p[1]-pts[1][1]).toFixed(2);el("point").textContent="该点模型误差 "+dist(pts[2])+" px；十帧匀速误差 "+dist(pts[3])+" px。";el("pos").textContent="第 "+row.frame+" 帧 → 第 "+row.target_frame+" 帧（"+(+sl.value+1)+" / "+rows.length+"）";
el("cap").textContent=s+" · "+h+" 帧 · 整段留出测试";el("methods").replaceChildren();for(const [k,v] of Object.entries(db.result.pose[h][s]))el("methods").insertRow().innerHTML=[labels[k],v.n,v.mean.toFixed(2),v.p90.toFixed(2)].map(x=>"<td>"+x+"</td>").join("");}
el("clip").onchange=el("h").onchange=()=>show(true);el("step").oninput=()=>show(false);show(true);
