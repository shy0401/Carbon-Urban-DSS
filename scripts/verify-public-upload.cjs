const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
  const base=fs.readFileSync('data/deployment/public-url.txt','utf8').trim();
  const c=JSON.parse(fs.readFileSync('.secrets/prototype-credentials.json','utf8').replace(/^\uFEFF/,''));
  // Valid existing source plus JSON whitespace tests the proxy body limit without inventing observations.
  const original=fs.readFileSync('data/raw/osm-boundary.geojson');
  const body=new FormData();body.set('dataset_type','zoning');body.set('source_crs','EPSG:4326');
  body.set('file',new Blob([Buffer.alloc(2*1024*1024,32),original],{type:'application/geo+json'}),'boundary-preview.geojson');
  const response=await fetch(base+'/api/uploads/preview',{method:'POST',headers:{Authorization:'Basic '+Buffer.from(c.username+':'+c.password).toString('base64')},body,signal:AbortSignal.timeout(60000)});
  assert.equal(response.status,200,'2MB upload must reach application');
  const result=await response.json();assert(result.id);
  fs.writeFileSync('data/deployment/upload-check.json',JSON.stringify({status:response.status,preview_id:result.id,imported:false},null,2));
  console.log(JSON.stringify({upload:'passed',imported:false}));
})().catch(e=>{console.error(e.message);process.exitCode=1});
