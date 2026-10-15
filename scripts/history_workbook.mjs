import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
const require=createRequire(import.meta.url);
const deps=process.env.FINBRIDGE_ARTIFACT_MODULES||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool',{paths:[deps]})).href);
const values=JSON.parse(await fs.readFile(process.argv[2],'utf8')),output=process.argv[3];
const wb=Workbook.create(),s=wb.worksheets.add('企业财务数据'),last=values.length;
s.getRange(`A1:E${last}`).values=values;s.showGridLines=false;
s.getRange(`A1:E${last}`).format.font={name:'Microsoft YaHei',size:11,color:'#183D35'};
s.getRange(`A1:E${last}`).format.rowHeight=26;
s.getRange('A:A').format.columnWidth=27;s.getRange('B:B').format.columnWidth=49;s.getRange('C:E').format.columnWidth=25;
s.getRange('A1:E1').format.fill='#163F35';s.getRange('A1:E1').format.font={name:'Microsoft YaHei',size:11,bold:true,color:'#FFFFFF'};
s.getRange(`C6:E${last}`).setNumberFormat('#,##0.00########;[Red](#,##0.00########);0.00');
s.getRange(`C2:E${last}`).format.font={name:'Microsoft YaHei',size:11,color:'#1755A5'};
s.getRange(`B6:B${last}`).format.wrapText=true;
for(let i=5;i<values.length;i++)if(String(values[i][1]).length>23)s.getRange(`A${i+1}:E${i+1}`).format.rowHeight=44;
s.freezePanes.freezeRows(1);wb.recalculate();
await fs.mkdir(path.dirname(output),{recursive:true});await (await SpreadsheetFile.exportXlsx(wb)).save(output);
if(process.argv.includes('--preview')){
 const check=await wb.inspect({kind:'table',range:'企业财务数据!A1:E20',include:'values,formulas',tableMaxRows:20,tableMaxCols:5});await fs.writeFile(output+'.inspect.ndjson',check.ndjson);
 for(const [name,range] of [['top','A1:E24'],['bottom',`A25:E${last}`]]){const png=await wb.render({sheetName:'企业财务数据',range,scale:1,format:'png'});await fs.writeFile(output+'.'+name+'.png',new Uint8Array(await png.arrayBuffer()));}
}
