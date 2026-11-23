// Render the read-only SQLite snapshot into a workbook for research use.
import fs from "node:fs/promises";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const [dbPath, outputPath, previewDir] = process.argv.slice(2);
const db = new DatabaseSync(dbPath, { readOnly: true });
const query = sql => db.prepare(sql).all();
const methods = query("SELECT * FROM method ORDER BY sort_order");
const classes = query("SELECT class_id FROM defect_class ORDER BY sort_order").map(r => r.class_id);
const catalog = query(`SELECT * FROM v_ta ORDER BY CASE scope WHEN 'current' THEN 1 WHEN 'rejected' THEN 2 ELSE 3 END,
                       base_name, case_id IS NOT NULL, display_name, ta_id`);
const ta = new Map(catalog.map(t => [t.ta_id, t]));
const method = new Map(methods.map(m => [m.method_id, m]));
const index = new Map(catalog.map((t,i) => [t.ta_id,i]));
const order = (a,b) => index.get(a.ta_id) - index.get(b.ta_id)
  || method.get(a.method_id).sort_order - method.get(b.method_id).sort_order;
const runs = query("SELECT * FROM v_ta_method").sort(order);
const run = new Map(runs.map(r => [r.ta_id+"/"+r.method_id, r]));
const metrics = query("SELECT s.* FROM v_method_summary s JOIN method USING (method_id) ORDER BY sort_order");
const injected = query("SELECT * FROM v_class_summary");
const byInjection = new Map(injected.map(r => [r.method_id+"/"+r.class_id,r]));
const nativeTotals = new Map(query(`SELECT method_id, class_id, sum(total) AS total FROM v_ta_method_class
    JOIN ta USING (ta_id) WHERE scope='current' GROUP BY method_id,class_id`).map(r=>[r.method_id+"/"+r.class_id,r.total]));
const supported = new Set(query("SELECT DISTINCT method_id FROM method_class").map(r=>r.method_id));
const byClass = query("SELECT * FROM v_ta_method_class")
  .filter(r => r.class_id!=="unmapped" || !supported.has(r.method_id) || r.total>0)
  .sort((a,b) => order(a,b) || [...classes,"unmapped"].indexOf(a.class_id) - [...classes,"unmapped"].indexOf(b.class_id));
const targets = query(`SELECT t.*,d.class_id,d.decision FROM label_target t JOIN defect d USING(ta_id,defect_id)`)
  .sort((a,b)=>index.get(a.ta_id)-index.get(b.ta_id)||a.defect_id.localeCompare(b.defect_id)||a.role.localeCompare(b.role)||a.first_line-b.first_line);
const targetRuns = new Map(query("SELECT * FROM v_target_result").map(t=>[t.target_id+"/"+t.method_id,t]));
const reports = query("SELECT r.*,a.output_path FROM v_report r JOIN analysis_run a USING(ta_id,method_id)").sort(order);
const key = r => [r.ta_id,r.method_id,r.report_ref].join("/");
function group(rows, keyOf) {
  const out = new Map();
  for (const r of rows) {
    const k=keyOf(r);
    if(!out.has(k)) out.set(k,[]);
    out.get(k).push(r);
  }
  return out;
}
const reportLocs=group(query("SELECT * FROM report_location ORDER BY ta_id,method_id,report_ref,ordinal"),key);
const matched=group(query(`SELECT m.*,t.role FROM v_match m JOIN label_target t USING(target_id)
                           ORDER BY m.ta_id,m.method_id,m.report_ref,t.defect_id,t.role`),key);
const approvedCount=db.prepare(`SELECT count(*) AS n FROM defect JOIN ta USING(ta_id)
                                  WHERE scope='current' AND decision='approved'`).get().n;
const statusTime=db.prepare("SELECT llm_status_utc FROM snapshot").get().llm_status_utc;
db.close();

const scopeName={current:"現行",rejected:"人手却下",retired_normal:"旧正常対照"};
const reviewName={normal:"正常対照",approved:"全件承認",partially_approved:"一部承認",unreviewed:"未レビュー",rejected:"却下",in_review:"レビュー中"};
const labelDecision={approved:"承認",rejected:"却下",unreviewed:"未レビュー",in_review:"レビュー中"};
const stateName={completed:"完了",partial:"部分解析",running:"実行中",pending:"未着手",failed:"失敗"};
const shortName={"DITING":"DITING 公開版","DITING-GP11":"DITING 1.1互換","CodeQL":"標準CodeQL","Semgrep":"Semgrep CE","TFI-Qwen":"TFI＋Qwen"};
const cls=c=>c==="unmapped" || c==null?"未対応付け":c;
const age=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hour12:false}).format(new Date(statusTime));
const live=catalog.filter(c=>c.scope==="current");
const old=catalog.filter(c=>c.scope!=="current");
const nDef=live.filter(t=>t.case_id!==null).length;
const unavailable="—";
const show=v=>v??unavailable;
const pair=(a,b)=>a==null?unavailable:`${a} / ${show(b)}`;
const fmtLoc=p=>p.path+":"+p.first_line+(p.first_line===p.last_line?"":"–"+p.last_line);
const wb=Workbook.create();
const [summary, overview, detail, breakdown, labelSheet, evidence, terms]=
  ["サマリー","TA別比較","TA・手法別","分類別内訳","ラベル位置","報告明細","集計条件"].map(n=>wb.worksheets.add(n));
const font="Hiragino Sans", navy="#17394C", teal="#14695E", ink="#183748", muted="#375666";
const pale="#E8F1F3", green="#DAF1E5", amber="#FAEDD3", white="#FFFFFF";
const expected=[];
function column(n){let v="";for(;n;n=Math.floor((n-1)/26))v=String.fromCharCode(65+(n-1)%26)+v;return v;}
function area(s,row,c,height,width){return s.getRangeByIndexes(row-1,c-1,height,width);}
function write(s,row,c,matrix){if(matrix.length)area(s,row,c,matrix.length,matrix[0].length).values=matrix;}
function banner(s,row,first,last,value,bg=teal,fg=white,size=11,height=23){
  const r=area(s,row,first,1,last-first+1);
  if(last>first)r.merge();
  r.values=[[value]];
  r.format.fill=bg;r.format.font={name:font,bold:true,color:fg,size};
  r.format.rowHeight=height;r.format.verticalAlignment="center";
}
function layout(s,widths,height,title,subtitle){
  s.showGridLines=false;
  const all=area(s,1,1,height,widths.length);
  all.format.font={name:font,size:10,color:ink};all.format.rowHeight=19;all.format.verticalAlignment="center";
  widths.forEach((w,i)=>{area(s,1,i+1,height,1).format.columnWidthPx=w;});
  banner(s,1,1,widths.length,title,navy,white,18,37);
  banner(s,2,1,widths.length,subtitle,pale,muted,10,26);
}
function table(s,name,row,headers,data,filter=true){
  write(s,row,1,[headers,...data]);
  if(data.length){
    const t=s.tables.add(`A${row}:${column(headers.length)}${row+data.length}`,true,name);
    t.style="TableStyleLight9";t.showBandedRows=false;t.showFilterButton=filter;
  }
  const h=area(s,row,1,1,headers.length);
  h.format.fill=navy;h.format.font={name:font,bold:true,color:white,size:10};
  h.format.rowHeight=33;h.format.wrapText=true;
}
function fixed(s,n=2){s.freezePanes.freezeRows(4);s.freezePanes.freezeColumns(n);}
function cellFill(s,row,c,fill){s.getCell(row-1,c-1).format.fill=fill;}
function formula(s,row,c,f,value){
  s.getCell(row-1,c-1).formulas=[[f]]; expected.push([s,row,c,value]);
}
function centered(s,row,c,rows,cols){if(rows>0)area(s,row,c,rows,cols).format.horizontalAlignment="center";}

// One measured or pending TA/method pair per row; this is the numeric source of the headline.
const runData=runs.map(r=>{
  const t=ta.get(r.ta_id),obs=r.total!=null;
  return [r.ta_id,t.display_name,scopeName[t.scope],t.case_id?"不備TA":"正常対照",method.get(r.method_id).display_name,
    stateName[r.status],r.total,r.within_approved,r.same_approved,r.within_public,r.same_public,
    obs?r.labels_approved:null,r.labels_hit_approved,obs?r.comparable_approved:null,r.labels_same_approved,r.output_path];
});
layout(detail,[73,244,101,98,199,95,88,112,122,112,122,120,125,125,133,610],4+runs.length,
  "TAと手法ごとの検知件数","1行は1個のTAと1手法の組。件数は数値、出力待ちおよび適用外は空欄です。原出力はTA-BenchGenからの相対パスです。");
table(detail,"Runs",4,["入力ID","TA名","対象","TA区分","手法","状態","総報告","承認範囲内","うち承認分類一致","公開範囲内","うち公開分類一致","位置照合ラベル数","位置一致ラベル数","分類照合ラベル数","位置・分類一致ラベル数","原出力"],runData);
centered(detail,5,7,runs.length,9);fixed(detail);

layout(summary,[205,104,121,127,122,114,131,137],35,
  "TAベンチマーク評価サマリー","現行ベンチマーク　　Qwenの保存結果を "+age+"（日本時間）時点で集計");
for(const [i,[caption,value,unit]] of [["評価対象",live.length,"個"],["正常対照",live.length-nDef,"個"],
  ["不備TA",nDef,"個"],["人手承認ラベル",approvedCount,"件"]].entries()){
  const start=1+2*i;
  banner(summary,4,start,start+1,caption,pale,muted,10,20);
  banner(summary,5,start,start+1,value,white,teal,22,34);
  area(summary,4,start,2,2).format.horizontalAlignment="center";
  area(summary,5,start,1,2).setNumberFormat('0"'+unit+'"');
}
banner(summary,7,1,8,"手法別の報告数（件）");
table(summary,"SummaryMethods",8,["手法","出力あり（個）","部分解析（個）","正常対照の報告","不備TAの報告","総報告","承認範囲内","うち分類一致"],
  metrics.map(m=>[method.get(m.method_id).display_name,...Array(7).fill(null)]),false);
const rr=c=>`'TA・手法別'!$${c}$5:$${c}$${4+runs.length}`;
for(const [i,m] of metrics.entries()){
  const row=9+i,common=rr("C")+', "現行", '+rr("E")+', $A'+row;
  const count=status=>`COUNTIFS(${common},${rr("F")},"${status}")`;
  formula(summary,row,2,"="+count("完了")+"+"+count("部分解析"),m.with_output);
  formula(summary,row,3,"="+count("部分解析"),m.partial);
  for(const [c,range,filter,result] of [[4,"G","正常対照",m.control_reports],[5,"G","不備TA",m.defective_reports],
      [7,"H",null,m.reports_at_approved],[8,"I",null,m.reports_same_approved]]){
    if(result==null){write(summary,row,c,[[unavailable]]);continue;}
    const extra=filter?','+rr("D")+', "'+filter+'"':"";
    formula(summary,row,c,`=SUMIFS(${rr(range)},${common}${extra})`,result);
  }
  if(m.total_reports==null)write(summary,row,6,[[unavailable]]);
  else formula(summary,row,6,`=SUM(D${row}:E${row})`,m.total_reports);
  if(m.partial)cellFill(summary,row,3,amber);
  if(m.without_output)cellFill(summary,row,2,amber);
  if(m.reports_at_approved>0)cellFill(summary,row,7,green);
  if(m.reports_same_approved>0)cellFill(summary,row,8,green);
}
centered(summary,9,2,methods.length,7);
const pending=runs.filter(r=>ta.get(r.ta_id).scope==="current" && r.total==null)
  .map(r=>`${shortName[r.method_id]} ${r.ta_id} ${ta.get(r.ta_id).display_name}（${stateName[r.status]}）`);
banner(summary,15,1,8,pending.length?"未完了　"+pending.join("、"):"現行の全TA・手法に出力があります。",pale,muted,10,24);
banner(summary,17,1,8,"注入した不備分類ごとの一致ラベル数（件）");
banner(summary,18,1,8,"各セルは「位置一致 / うち分類一致」。同じ不備IDは1件と数え、分類を対応付けていない欄は — で示します。",pale,muted,10,23);
const labelSummary=classes.map(c=>{
  const cells=methods.map(m=>byInjection.get(m.method_id+"/"+c));
  return [c,cells[0].approved_labels,...cells.map(x=>pair(x.labels_hit,x.labels_same))];
});
table(summary,"SummaryLabels",19,["注入分類","承認ラベル数",...methods.map(m=>shortName[m.method_id])],labelSummary,false);
centered(summary,20,2,classes.length,methods.length+1);
for(const [i,c] of classes.entries())for(const [j,m] of methods.entries()){
  if(byInjection.get(m.method_id+"/"+c).labels_hit>0)cellFill(summary,20+i,3+j,green);
}
banner(summary,26,1,8,"解析器が報告した分類の内訳（件）");
const nativeRows=methods.map(m=>[m.display_name,
  ...[...classes,"unmapped"].map(c=>show(nativeTotals.get(m.method_id+"/"+c))),
  show(metrics.find(x=>x.method_id===m.method_id).total_reports)]);
table(summary,"SummaryNative",27,["手法",...classes,"未対応付け","総報告"],nativeRows,false);
centered(summary,28,2,methods.length,classes.length+2);
banner(summary,34,1,8,"報告分類は各手法の主分類を使用。標準CodeQLとSemgrepの個別規則は「未対応付け」に集計します。",pale,muted,10,24);

// Display the paired measurements compactly; the Runs table retains numeric columns for filtering.
const head=["入力ID","TA名","人手判定","承認ラベル数",...methods.map(m=>shortName[m.method_id]),"解析上の注記"];
function caseRow(t){
  const rr=methods.map(m=>run.get(t.ta_id+"/"+m.method_id));
  const note=rr.filter(r=>r.status!=="completed").map(r=>shortName[r.method_id]+" "+stateName[r.status]).join("、");
  return [t.ta_id,t.display_name,reviewName[t.review],rr[0].labels_approved,
    ...rr.map(r=>r.total==null?stateName[r.status]:pair(r.total,r.within_approved)),note];
}
layout(overview,[74,240,118,108,118,130,111,111,109,199],9+catalog.length,
   "TA別の検知結果","各セルは「総報告 / 承認ラベル範囲内の報告」。正常対照と承認ラベルのないTAは右側を — と表示します。");
banner(overview,3,1,10,`現行の不備TA・正常対照　${live.length}個`,teal,white,11,22);
table(overview,"CurrentTAs",4,head,live.map(caseRow));
const archiveHeader=8+live.length;
banner(overview,archiveHeader-1,1,10,`参考　人手却下の不備TA・旧正常対照　${old.length}個`,muted);
table(overview,"ArchivedTAs",archiveHeader,head,old.map(caseRow));
for(const [list,first] of [[live,5],[old,archiveHeader+1]]){
  centered(overview,first,4,list.length,6);
  list.forEach((t,i)=>{
    for(const [j,m] of methods.entries()){
      const r=run.get(t.ta_id+"/"+m.method_id);
      if(r.within_approved>0)cellFill(overview,first+i,5+j,green);
      else if(r.total==null)cellFill(overview,first+i,5+j,amber);
    }
  });
}
fixed(overview);

const distribution=byClass.map(r=>[r.ta_id,ta.get(r.ta_id).display_name,scopeName[ta.get(r.ta_id).scope],
  shortName[r.method_id],cls(r.class_id),stateName[r.status],r.total,r.within_approved,r.same_approved,r.within_public,r.same_public]);
layout(breakdown,[75,245,108,142,126,98,100,117,133,117,133],4+distribution.length,
  "TA・報告分類別の内訳","報告側の分類ごとに1行。対応する分類の0件を含みます。個別規則だけを持つ手法は「未対応付け」にまとめます。");
table(breakdown,"ReportClasses",4,["入力ID","TA名","対象","手法","報告分類","状態","総報告","承認範囲内","うち承認分類一致","公開範囲内","うち公開分類一致"],distribution);
centered(breakdown,5,7,distribution.length,5);fixed(breakdown);

const targetData=targets.map(t=>{
  const benchmarkSource=ta.get(t.ta_id).benchmark_path;
  return [t.ta_id,ta.get(t.ta_id).display_name,t.defect_id,t.class_id,labelDecision[t.decision],t.role,
    t.is_public?(t.is_approved?"公開・承認":"公開のみ"):"承認時追加",fmtLoc(t),
    ...methods.map(m=>{const r=targetRuns.get(t.target_id+"/"+m.method_id);return r.hits==null?stateName[r.status]:pair(r.hits,r.same);}),
    t.function_name,path.posix.join(path.posix.dirname(benchmarkSource),t.is_public?"labels.json":"label_history.json")];
});
layout(labelSheet,[75,235,75,100,103,113,113,250,120,130,115,115,115,218,505],4+targetData.length,
   "不備ラベルのソース位置","1行は1か所の照合位置。各手法のセルは「位置一致報告 / うち分類一致報告」。承認位置・公開位置をそれぞれ表示します。");
table(labelSheet,"LabelLocations",4,["入力ID","TA名","不備ID","ラベル分類","人手判定","役割","位置の出典","ファイル・行",...methods.map(m=>shortName[m.method_id]),"関数","位置の記録"],targetData);
centered(labelSheet,5,9,targets.length,methods.length);fixed(labelSheet);
targets.forEach((t,i)=>methods.forEach((m,j)=>{if(targetRuns.get(t.target_id+"/"+m.method_id).hits>0)cellFill(labelSheet,5+i,9+j,green);}));

const refs=m=>[...new Set(m.map(x=>[x.defect_id,x.label_class,x.role].join("/")))].join("、")||null;
const reportData=reports.map(r=>{
  const loc=reportLocs.get(key(r)), hits=matched.get(key(r))??[];
  return [r.ta_id,ta.get(r.ta_id).display_name,scopeName[ta.get(r.ta_id).scope],shortName[r.method_id],
    r.report_ref,cls(r.reported_class),r.rule_name,loc.map(fmtLoc).join("、"),
    loc.map(l=>l.first_column==null?"":l.first_column+"–"+l.last_column).filter(Boolean).join("、")||null,
    refs(hits.filter(h=>h.is_approved)),refs(hits.filter(h=>h.is_public)),r.output_path];
});
layout(evidence,[75,240,100,137,143,116,248,258,106,177,177,630],4+reportData.length,
   "解析器の個別報告","1行は原出力の1報告。複数の位置がある場合も報告IDは1つです。ファイル・行、元の規則名、一致した不備IDから確認できます。");
table(evidence,"Findings",4,["入力ID","TA名","対象","手法","報告ID","報告分類","元の規則名","ファイル・行","列範囲","承認位置に一致","公開位置に一致","原出力"],reportData);
fixed(evidence);

const definitions=[
 ["対象","現行は benchmark/defective と benchmark/normal。人手却下の不備TAと旧正常対照の測定値はTA別比較の参考表に掲載します。"],
 ["単位","1件はDITINGの最終リストの1要素、SARIF・Semgrepの1 result、またはQwenの統合後の1 vulnerabilityです。同じ座標の別報告も原出力どおりに数えます。"],
 ["位置一致","同じ入力ID・相対ファイルの行区間が1行以上重なる場合。開始・終了行を含み、影響位置 effect と保護位置 protection が対象です。列や説明文中の行番号は使用しません。"],
 ["公開・承認","公開位置は labels.json の detector_targets。承認位置は label_history.json の不備単位の承認とその時点の修正を反映。T30のD1では104行の公開位置に83行の保護位置が加わります。"],
 ["件数の違い","範囲内報告は同じ報告IDを1件、位置一致ラベルは同じTA内の同じ不備IDを1件と数えます。1件の報告が複数の照合位置に重なっても範囲内報告は1件です。"],
 ["分類","分類一致には報告側の主分類とラベル分類の一致も必要です。Qwenは primary_rule_id を使います。ORDERのC1とC2は同じ分類に属する別々の不備IDです。"],
 ["空欄と0","0は適用できる条件で該当件数が0。空欄・—は出力待ち、対象ラベルなし、または分類対応なしです。部分解析は「出力あり」の内数で、得られた報告数を表示します。"],
 ["元データ","benchmark-results.db の ta、defect、label_target、analysis_run、report、report_location が対応する記録を保持します。原出力のパスはTA-BenchGenからの相対パスです。"],
 ["未レビュー・却下","PKCS#11のT33は未レビューのORDER 2件、T30のD2は却下です。各位置の報告は公開位置の指標で参照できます。"],
];
layout(terms,[185,905],4+definitions.length,"集計条件","報告やラベルの件数を引用するときの基準");
table(terms,"Definitions",4,["項目","集計方法"],definitions,false);
area(terms,5,2,definitions.length,1).format.wrapText=true;area(terms,5,1,definitions.length,2).format.rowHeight=40;
terms.freezePanes.freezeRows(4);

wb.recalculate();
for(const [s,r,c,v] of expected){
  const got=s.getCell(r-1,c-1).values[0][0];
  if(got!==v)throw Error(`${s.name}!${column(c)}${r} = ${got}, SQLite = ${v}`);
}
const scan=await wb.inspect({kind:"match",searchTerm:"#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options:{useRegex:true,maxResults:5},maxChars:700});
if(scan.ndjson.includes('"kind":"match"'))throw Error(scan.ndjson);
if(previewDir){
  const ranges=["A1:H34","A1:J12","A1:P10","A1:K11","A1:O11","A1:L10","A1:B11"];
  for(const [i,s] of [summary,overview,detail,breakdown,labelSheet,evidence,terms].entries()){
    const blob=await wb.render({sheetName:s.name,range:ranges[i],format:"png",scale:1});
    await fs.writeFile(path.join(previewDir,s.name+".png"),new Uint8Array(await blob.arrayBuffer()));
  }
}
const result=await SpreadsheetFile.exportXlsx(wb);
await result.save(outputPath);
