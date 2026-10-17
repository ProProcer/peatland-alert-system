const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname+'/app.js','utf8');
const cells=JSON.parse(fs.readFileSync(__dirname+'/../data/demo/role_a_real/regional_40/cells.geojson','utf8')).features;
let view, selected, scrolled=false;
const context={window:{addEventListener(){},dispatchEvent(){}},Event:class {},MouseEvent:class {},matchMedia:()=>({matches:true}),regionalCells:()=>cells,project:([x,y])=>[x*50,-y*50],regionView:[0,0,900,650],setMapView:v=>view=v,document:{querySelectorAll:()=>cells.map(row=>({dataset:{cellId:row.properties.cell_id},dispatchEvent(){selected=row.properties.cell_id;},focus(){}})),querySelector:()=>({scrollIntoView(){scrolled=true;}})}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('function focusMonitoringCell('),source.indexOf('function mapPixelScale(')),context);
for(const cell of cells){assert(context.focusMonitoringCell(cell.properties.cell_id));assert.equal(selected,cell.properties.cell_id);const points=cell.geometry.coordinates[0].map(context.project);for(const [x,y] of points){assert(x>=view[0]&&x<=view[0]+view[2]);assert(y>=view[1]&&y<=view[1]+view[3]);}const cellWidth=Math.max(...points.map(p=>p[0]))-Math.min(...points.map(p=>p[0]));assert(cellWidth/view[2]*650>65);}
assert(scrolled);assert.equal(context.focusMonitoringCell('missing'),false);
console.log('PASS: locate centers all 40 cells, fits each square at visible zoom, selects its marker and scrolls to map.');
