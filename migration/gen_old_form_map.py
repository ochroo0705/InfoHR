import json,re,collections
f=json.load(open('forms.json',encoding='utf-8'))
def is_app(n):return n.startswith(('frm','Frm','dm1','QR','WUWIZ','Select'))
def walk(o,fn,parent=None):
    fn(o,parent)
    for k in o['kids']:walk(k,fn,o)
def tables(sql):
    s=re.sub(r"--[^\n]*|/\*.*?\*/",' ',sql,flags=re.S)
    return sorted(set(m.lower() for m in re.findall(r'(?i)\b(?:from|join)\s+"?([a-z_][a-z0-9_]*)"?',s))-{'select','select'})
def sqltext(v):
    return '\n'.join(v) if isinstance(v,list) else str(v)
out=['# Old program (HumanCapitalXE4.exe) — full form map\n',
'Generated 2026-10-21 by reading the form definitions (binary DFM) stored inside `E:\humancapital\HumanCapitalXE4.exe` (read-only). Every screen, its datasets (SQL + key fields) and the data-bound controls. `XE` datasets are the program\'s own dataset class: the table they save to is the main table of their SQL and the key fields name the row.\n',
'Limits: form data only. Extra writes done in Pascal code or by database triggers are not here (see `trigger-parity.md` and `legacy-logic/`).\n']
tabidx=collections.defaultdict(set)
forms=[x for x in f if is_app(x['name'])]
for fm in sorted(forms,key=lambda x:x['name'].lower()):
    ds={};srcs={};ctrls=[]
    def g(o,p):
        pr=o['props']
        if 'SQL.Strings' in pr:ds[o['name']]=o
        elif o['class'] in('TDataSource','TXEDataSource') or 'DataSet' in pr and o['class'].endswith('DataSource'):
            srcs[o['name']]=pr.get('DataSet')
        fld=pr.get('DataField') or pr.get('DataBinding.FieldName') or pr.get('FieldName')
        if fld and o['class'] not in('TIntegerField',) and not o['class'].endswith('Field'):
            ctrls.append((o['name'],o['class'],pr.get('DataSource'),fld,pr.get('Caption') or pr.get('Properties.Caption') or pr.get('Hint') or ''))
    walk(fm,g)
    cap=fm['props'].get('Caption','')
    out.append(f"\n## {fm['name']} — {cap}\n")
    if not ds and not ctrls:out.append('_no datasets or bound fields_\n');continue
    for n,o in ds.items():
        sql=sqltext(o['props']['SQL.Strings']);t=tables(sql)
        for x in t:tabidx[x].add(fm['name'])
        out.append(f"**Dataset `{n}`** — tables: {', '.join('`'+x+'`' for x in t) or '?'}"+(f" — key: `{o['props']['KeyFields']}`" if 'KeyFields' in o['props'] else '')+(f" — master: `{o['props']['MasterSource']}`" if 'MasterSource' in o['props'] else ''))
        out.append('```sql\n'+sql.strip()+'\n```')
    if ctrls:
        out.append('\nBound controls (control, class, source→dataset, field, caption):\n')
        out.append('| Control | Class | Source→Dataset | Field | Caption |\n|---|---|---|---|---|')
        for c in ctrls:
            src=c[2]
            dsn=srcs.get(src.lstrip('@')) if isinstance(src,str) else None
            dsn=dsn.lstrip('@') if isinstance(dsn,str) else dsn
            out.append(f"| {c[0]} | {c[1]} | {src}→{dsn} | `{c[3]}` | {str(c[4])[:40]} |")
open('form-map.md','w',encoding='utf-8').write('\n'.join(out)+'\n')
idx=['# Old program — table index (tables → forms whose datasets read them)\n','| Table | Forms |','|---|---|']
for t in sorted(tabidx):idx.append(f"| `{t}` | {', '.join(sorted(tabidx[t]))} |")
open('table-index.md','w',encoding='utf-8').write('\n'.join(idx)+'\n')
print(len(forms),'app forms',len(tabidx),'tables'); 
