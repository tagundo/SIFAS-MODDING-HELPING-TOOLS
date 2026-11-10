/* Generated depth-order oracle for the actual viewer browser regression. No product code is imported.
 * Calibrated with Chromium ANGLE/SwiftShader, 24-bit depth, 4-sample AA.
 * Camera [0,.6,6], target [0,.6,0], far100, gap.0005:
 * near.001: front-first red (wrong), rear-first green;
 * near.0067/.008485/.01: green for both draw orders.
 * The expected color is determined by source-triangle ray intersections, not
 * by the candidate near policy or its depth-quantization formula.
 */
const DEFAULTS = Object.freeze({halfWidth:.6, yMin:0, yMax:1.2, rearZ:0, gap:.0005});
const FRONT = 'DepthOracleFrontGreen', REAR = 'DepthOracleRearRed';
function planeTriangles(o=DEFAULTS) {
  const quad=z=>[[-o.halfWidth,o.yMin,z],[o.halfWidth,o.yMin,z],[o.halfWidth,o.yMax,z],[-o.halfWidth,o.yMax,z]];
  const triangles=q=>[[q[0],q[1],q[2]],[q[0],q[2],q[3]]];
  return [{name:FRONT,color:[0,255,0,255],triangles:triangles(quad(o.rearZ+o.gap))},
    {name:REAR,color:[255,0,0,255],triangles:triangles(quad(o.rearZ))}];
}
function appendDepthPlanes(input, options={}) {
  const o=Object.assign({},DEFAULTS,options), buffer=input.glb;
  const jsonLength=buffer.readUInt32LE(12), doc=JSON.parse(buffer.subarray(20,20+jsonLength).toString());
  const oldBin=buffer.subarray(28+jsonLength,28+jsonLength+buffer.readUInt32LE(20+jsonLength));
  const chunks=[oldBin];let length=oldBin.length;
  function attr(values,Type,type,componentType,count,bounds){
    const pad=(4-length%4)%4;if(pad){chunks.push(Buffer.alloc(pad));length+=pad;}
    const data=Buffer.from(new Type(values).buffer), bv=doc.bufferViews.length;
    doc.bufferViews.push({buffer:0,byteOffset:length,byteLength:data.length});chunks.push(data);length+=data.length;
    const accessor=doc.accessors.length;doc.accessors.push(Object.assign({bufferView:bv,componentType,type,count},bounds));return accessor;
  }
  const normal=attr([0,0,1,0,0,1,0,0,1,0,0,1],Float32Array,'VEC3',5126,4);
  const indices=attr([0,1,2,0,2,3],Uint16Array,'SCALAR',5123,6);
  for(const [name,z,color] of [[FRONT,o.rearZ+o.gap,[0,1,0,1]],[REAR,o.rearZ,[1,0,0,1]]]){
    const positions=attr([-o.halfWidth,o.yMin,z,o.halfWidth,o.yMin,z,o.halfWidth,o.yMax,z,-o.halfWidth,o.yMax,z],Float32Array,'VEC3',5126,4,
      {min:[-o.halfWidth,o.yMin,z],max:[o.halfWidth,o.yMax,z]});
    const material=doc.materials.length;doc.materials.push({name,pbrMetallicRoughness:{baseColorFactor:color,metallicFactor:0,roughnessFactor:1},doubleSided:true,extensions:{KHR_materials_unlit:{}}});
    const mesh=doc.meshes.length;doc.meshes.push({name,primitives:[{attributes:{POSITION:positions,NORMAL:normal},indices,material}]});
    const node=doc.nodes.length;doc.nodes.push({name,mesh});doc.scenes[doc.scene||0].nodes.push(node);
  }
  doc.extensionsUsed=Array.from(new Set([...(doc.extensionsUsed||[]),'KHR_materials_unlit']));doc.buffers[0].byteLength=length;
  const json=Buffer.from(JSON.stringify(doc)),jp=Buffer.concat([json,Buffer.alloc((4-json.length%4)%4,32)]);
  const bin=Buffer.concat(chunks),bp=Buffer.concat([bin,Buffer.alloc((4-bin.length%4)%4)]);
  const header=Buffer.alloc(12),jh=Buffer.alloc(8),bh=Buffer.alloc(8);
  header.writeUInt32LE(0x46546c67,0);header.writeUInt32LE(2,4);header.writeUInt32LE(28+jp.length+bp.length,8);
  jh.writeUInt32LE(jp.length);jh.writeUInt32LE(0x4e4f534a,4);bh.writeUInt32LE(bp.length);bh.writeUInt32LE(0x004e4942,4);
  return Object.assign({},input,{glb:Buffer.concat([header,jh,jp,bh,bp]),depthOracle:{options:o,planes:planeTriangles(o),camera:{position:[0,.6,6],target:[0,.6,0],fov:35},names:{front:FRONT,rear:REAR}}});
}
function rayTriangle(origin,direction,triangle){
  const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const e1=sub(triangle[1],triangle[0]),e2=sub(triangle[2],triangle[0]),p=cross(direction,e2),det=dot(e1,p);
  if(Math.abs(det)<1e-12)return null;
  const inv=1/det,t=sub(origin,triangle[0]),u=dot(t,p)*inv;if(u<0||u>1)return null;
  const q=cross(t,e1),v=dot(direction,q)*inv;if(v<0||u+v>1)return null;
  const distance=dot(e2,q)*inv;return distance>=0?distance:null;
}
function centerRayOracle(cameraPosition,cameraTarget,planes=planeTriangles()){
  const delta=cameraTarget.map((v,i)=>v-cameraPosition[i]),norm=Math.hypot(...delta),direction=delta.map(v=>v/norm),hits=[];
  for(const plane of planes){const distances=plane.triangles.map(t=>rayTriangle(cameraPosition,direction,t)).filter(v=>v!==null);if(distances.length)hits.push({name:plane.name,color:plane.color,distance:Math.min(...distances)});}
  hits.sort((a,b)=>a.distance-b.distance);return {expected:hits[0]||null,hits};
}
// Can be passed directly to Playwright evaluate after serializing its source.
function setDepthOrder(root,frontFirst=true){
  root.traverse(object=>{if(!object.isMesh)return;
    if(object.name==='DepthOracleFrontGreen')object.renderOrder=frontFirst?100:101;
    else if(object.name==='DepthOracleRearRed')object.renderOrder=frontFirst?101:100;
    else object.renderOrder=-100;
  });
}
function classifyColor(rgba){return rgba[1]>200&&rgba[0]<30&&rgba[2]<30?'green':rgba[0]>200&&rgba[1]<30&&rgba[2]<30?'red':'other';}
module.exports={DEFAULTS,FRONT,REAR,planeTriangles,appendDepthPlanes,rayTriangle,centerRayOracle,setDepthOrder,classifyColor};
