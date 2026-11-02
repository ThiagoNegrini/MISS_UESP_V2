#!/usr/bin/env python3
"""Central de Controle UESP 2027 — servidor local com controle de chegada."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import unquote, urlparse, urlsplit
import hmac, os, secrets, sqlite3, json, socket, io, time, threading
from pathlib import Path
from email.parser import BytesParser
from email.policy import default
from datetime import datetime

HERE=Path(__file__).resolve().parent
AUDITION_DB=HERE/"banco_audicao.db"
CONTEST_DB=HERE/"banco_concurso.db"
AGULHA_DB=HERE/"banco_agulha_ouro.db"
DATABASES=(AUDITION_DB,CONTEST_DB,AGULHA_DB)
BACKUP_DIR=HERE/"backup de banco"
BACKUP_SET_RETENTION=30
CATEGORIES=["Rainha do Samba","Passista de Ouro","Diva do Samba (Plus Size)"]
PIN_FILE=HERE/"UESP_ACCESS_PIN.txt"
def load_access_pin():
    env_pin=os.environ.get("UESP_ACCESS_PIN","").strip()
    if env_pin: return env_pin,"environment"
    try:
        pin=next((line.strip() for line in PIN_FILE.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and not line.lstrip().startswith("#")),"")
    except OSError:
        pin=""
    if pin: return pin,"file"
    return secrets.token_urlsafe(8),"generated"

ACCESS_PIN,ACCESS_PIN_SOURCE=load_access_pin()
SESSIONS={}
DB_SCHEMAS_READY=set()
CONTEST_SCHEMA_READY=False
API_CONDITION=threading.Condition()
ACTIVE_API_REQUESTS=0
DATABASE_MAINTENANCE=False
SCORE_SYNC_REPORTS={}
SCORE_SYNC_REPORTS_LOCK=threading.Lock()

def dbconn(database=AUDITION_DB):
    """Abre o banco solicitado sem criar tabelas da Audição no banco do Concurso."""
    target=Path(database).resolve()
    con=sqlite3.connect(target,timeout=15)
    con.row_factory=sqlite3.Row
    # The server initializes all three databases before accepting requests.
    # Avoid repeating CREATE TABLE and PRAGMA work for every API call.
    if target in DB_SCHEMAS_READY:
        return con
    if target == AUDITION_DB.resolve():
        con.execute("""CREATE TABLE IF NOT EXISTS candidates (
          id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, name TEXT NOT NULL,
          imported_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(category,name))""")
        # Campos operacionais usados pela tela de chegada e pelas fotos/relatórios.
        # ALTER TABLE é aditivo: preserva os candidatos e os dados já existentes.
        candidate_columns={r[1] for r in con.execute("PRAGMA table_info(candidates)").fetchall()}
        for column,definition in (
            ("photo","TEXT"),("artistic_name","TEXT"),("mannequin","TEXT"),
            ("shoe_size","TEXT"),("body_size","TEXT")
        ):
            if column not in candidate_columns:
                con.execute(f"ALTER TABLE candidates ADD COLUMN {column} {definition}")
        con.execute("""CREATE TABLE IF NOT EXISTS arrivals (
          candidate_id INTEGER PRIMARY KEY, arrived_at TEXT NOT NULL, device TEXT DEFAULT 'Recepção',
          FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL, evaluator TEXT NOT NULL,
          communication REAL, samba REAL, updated_at TEXT NOT NULL, UNIQUE(candidate_id,evaluator),
          FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS evaluator_roster (
          stage TEXT NOT NULL, position INTEGER NOT NULL, evaluator TEXT NOT NULL,
          PRIMARY KEY(stage,position), UNIQUE(stage,evaluator))""")
        con.execute("""CREATE TABLE IF NOT EXISTS app_settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS audition_result_publication (
          candidate_id INTEGER PRIMARY KEY, category TEXT NOT NULL, position INTEGER NOT NULL,
          published_at TEXT NOT NULL, FOREIGN KEY(candidate_id) REFERENCES candidates(id) ON DELETE CASCADE)""")
    elif target == CONTEST_DB.resolve():
        con.execute("""CREATE TABLE IF NOT EXISTS evaluator_roster (
          stage TEXT NOT NULL, position INTEGER NOT NULL, evaluator TEXT NOT NULL,
          PRIMARY KEY(stage,position), UNIQUE(stage,evaluator))""")
        con.execute("""CREATE TABLE IF NOT EXISTS contest_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL, evaluator TEXT NOT NULL,
          aesthetics_sympathy REAL, communication_elegance REAL, samba REAL, updated_at TEXT NOT NULL,
          UNIQUE(candidate_id,evaluator))""")
    elif target == AGULHA_DB.resolve():
        con.execute("""CREATE TABLE IF NOT EXISTS evaluator_roster (
          position INTEGER PRIMARY KEY, evaluator TEXT NOT NULL UNIQUE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS agulha_scores (
          id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL,
          evaluator TEXT NOT NULL, score REAL NOT NULL, updated_at TEXT NOT NULL,
          UNIQUE(candidate_id,evaluator))""")
        con.execute("""CREATE TABLE IF NOT EXISTS app_settings (
          setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)""")
    else:
        con.close()
        raise ValueError("Banco de dados não reconhecido: "+str(target))
    DB_SCHEMAS_READY.add(target)
    return con

def ensure_contest_schema(con):
    global CONTEST_SCHEMA_READY
    if CONTEST_SCHEMA_READY: return
    con.execute("""CREATE TABLE IF NOT EXISTS contest_participants (id INTEGER PRIMARY KEY AUTOINCREMENT, source_candidate_id INTEGER NOT NULL UNIQUE, category TEXT NOT NULL, name TEXT NOT NULL, artistic_name TEXT DEFAULT '', mannequin TEXT DEFAULT '', shoe_size TEXT DEFAULT '', body_size TEXT DEFAULT '', photo TEXT DEFAULT '', migrated_at TEXT DEFAULT CURRENT_TIMESTAMP, audition_total REAL, audition_samba REAL, audition_partial_total REAL, audition_complete_evaluators INTEGER DEFAULT 0, audition_evaluators_with_data INTEGER DEFAULT 0, source_position INTEGER)""")
    con.execute("""CREATE TABLE IF NOT EXISTS contest_arrivals (candidate_id INTEGER PRIMARY KEY, arrived_at TEXT NOT NULL, device TEXT DEFAULT 'Recepção', status TEXT DEFAULT 'PRESENTE')""")
    con.execute("CREATE TABLE IF NOT EXISTS app_settings (setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)")
    cols={r[1] for r in con.execute("PRAGMA table_info(contest_participants)")}
    for name,definition in (("audition_total","REAL"),("audition_samba","REAL"),("audition_partial_total","REAL"),("audition_complete_evaluators","INTEGER DEFAULT 0"),("audition_evaluators_with_data","INTEGER DEFAULT 0"),("source_position","INTEGER")):
        if name not in cols: con.execute("ALTER TABLE contest_participants ADD COLUMN "+name+" "+definition)
    con.execute("""CREATE TABLE IF NOT EXISTS contest_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id INTEGER NOT NULL, evaluator TEXT NOT NULL, aesthetics_sympathy REAL, communication_elegance REAL, samba REAL, updated_at TEXT NOT NULL, UNIQUE(candidate_id,evaluator))""")
    CONTEST_SCHEMA_READY=True

def migrate_published_contest(audition_con, contest_con):
    ensure_contest_schema(contest_con)
    candidates=contest_eligible(audition_con)
    if len(candidates)!=25: raise ValueError("Migração cancelada: são necessários exatamente 25 classificados publicados; encontrados: "+str(len(candidates)))
    contest_con.execute("BEGIN IMMEDIATE")
    try:
        for c in candidates:
            contest_con.execute("""INSERT INTO contest_participants (source_candidate_id,category,name,artistic_name,mannequin,shoe_size,body_size,photo,audition_total,audition_samba,audition_partial_total,audition_complete_evaluators,audition_evaluators_with_data,source_position) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_candidate_id) DO UPDATE SET category=excluded.category,name=excluded.name,artistic_name=excluded.artistic_name,mannequin=excluded.mannequin,shoe_size=excluded.shoe_size,body_size=excluded.body_size,photo=excluded.photo,audition_total=excluded.audition_total,audition_samba=excluded.audition_samba,audition_partial_total=excluded.audition_partial_total,audition_complete_evaluators=excluded.audition_complete_evaluators,audition_evaluators_with_data=excluded.audition_evaluators_with_data,source_position=excluded.source_position""",
              (c["id"],c["category"],c["name"],c.get("artistic_name") or "",c.get("mannequin") or "",c.get("shoe_size") or "",c.get("body_size") or "",c.get("photo") or "",c.get("audition_total"),c.get("audition_samba"),c.get("audition_partial_total"),c.get("audition_complete_evaluators",0),c.get("audition_evaluators_with_data",0),c.get("position")))
        for score in contest_con.execute("SELECT id,candidate_id,evaluator FROM contest_scores ORDER BY id").fetchall():
            dest=contest_con.execute("SELECT id FROM contest_participants WHERE source_candidate_id=?",(score["candidate_id"],)).fetchone()
            if not dest or dest["id"]==score["candidate_id"]: continue
            exists=contest_con.execute("SELECT id FROM contest_scores WHERE candidate_id=? AND evaluator=?",(dest["id"],score["evaluator"])).fetchone()
            if exists: contest_con.execute("DELETE FROM contest_scores WHERE id=?",(score["id"],))
            else: contest_con.execute("UPDATE contest_scores SET candidate_id=? WHERE id=?",(dest["id"],score["id"]))
        contest_con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('contest_roster_migrated','1') ON CONFLICT(setting_key) DO UPDATE SET setting_value='1'")
        contest_con.commit()
    except Exception: contest_con.rollback(); raise
    return len(candidates)

def contest_participant_rows(con):
    ensure_contest_schema(con)
    return [dict(r) for r in con.execute("""SELECT id,source_candidate_id,category,name,photo,artistic_name,mannequin,shoe_size,body_size,source_position AS position,audition_total,audition_samba,audition_partial_total,audition_complete_evaluators,audition_evaluators_with_data FROM contest_participants ORDER BY source_position,category COLLATE NOCASE,name COLLATE NOCASE""").fetchall()]

def parse_multipart(content_type,body):
    msg=BytesParser(policy=default).parsebytes(b"Content-Type: "+content_type.encode("latin-1")+b"\r\nMIME-Version: 1.0\r\n\r\n"+body)
    if not msg.is_multipart(): return None,None
    for part in msg.iter_parts():
        if "form-data" in part.get("Content-Disposition","") and part.get_param("name",header="content-disposition")=="file":
            return part.get_filename() or "candidatos.xlsx",part.get_payload(decode=True)
    return None,None


def contest_eligible(con):
    """Retorna somente os participantes oficialmente publicados para o Concurso.

    A lista de classificação publicada na Audição é a fonte de verdade. Ter
    notas de Audição, por si só, não classifica uma pessoa para o Concurso.
    A lista final é limitada a 25 participantes.
    """
    published=con.execute("""
        SELECT c.id,c.category,c.name,c.photo,c.artistic_name,c.mannequin,
               c.shoe_size,c.body_size,p.position
        FROM audition_result_publication p
        JOIN candidates c ON c.id=p.candidate_id
        ORDER BY p.position ASC, c.category COLLATE NOCASE, c.name COLLATE NOCASE
        LIMIT 25
    """).fetchall()
    if not published:
        return []
    ids=[r["id"] for r in published]
    marks=",".join("?" for _ in ids)
    rs=con.execute(
        f"SELECT candidate_id,evaluator,communication,samba FROM scores WHERE candidate_id IN ({marks})",
        ids
    ).fetchall()
    by={}
    for r in rs:
        by.setdefault(r["candidate_id"],{})[r["evaluator"]]={
            "communication":r["communication"],"samba":r["samba"]}
    chosen=[]
    for candidate in published:
        ev=by.get(candidate["id"],{})
        available=[v for v in ev.values()
                   if v["communication"] is not None or v["samba"] is not None]
        complete=[v for v in available
                  if v["communication"] is not None and v["samba"] is not None]
        audition_total=round(sum(v["communication"]+v["samba"] for v in complete),1) if complete else None
        audition_samba=round(sum(v["samba"] for v in complete),1) if complete else None
        partial_total=round(sum((v["communication"] or 0)+(v["samba"] or 0) for v in available),1)
        chosen.append({"id":candidate["id"],"category":candidate["category"],"name":candidate["name"],
            "photo":candidate["photo"],"artistic_name":candidate["artistic_name"],
            "mannequin":candidate["mannequin"],"shoe_size":candidate["shoe_size"],
            "body_size":candidate["body_size"],"position":candidate["position"],
            "audition_total":audition_total,"audition_samba":audition_samba,
            "audition_partial_total":partial_total,
            "audition_complete_evaluators":len(complete),
            "audition_evaluators_with_data":len(available)})
    return chosen

def contest_result_rows(audition_con, contest_con):
    eligible=contest_participant_rows(contest_con)
    evaluator_count=contest_con.execute(
        "SELECT COUNT(*) FROM evaluator_roster WHERE stage='CONCURSO' AND TRIM(evaluator)<>''"
    ).fetchone()[0]
    scores=contest_con.execute("SELECT candidate_id,evaluator,aesthetics_sympathy,communication_elegance,samba FROM contest_scores").fetchall()
    by={}
    for r in scores:
        by.setdefault(r["candidate_id"],{})[r["evaluator"]]={"aesthetics_sympathy":r["aesthetics_sympathy"],"communication_elegance":r["communication_elegance"],"samba":r["samba"]}
    output=[]
    for c in eligible:
        ev=by.get(c["id"],{})
        women=c["category"].strip().casefold()!="passista de ouro"
        required=("communication_elegance","samba","aesthetics_sympathy") if women else ("communication_elegance","samba")
        complete=[v for v in ev.values() if all(v[k] is not None for k in required)]
        # A finalização depende da quantidade de avaliadores cadastrados para o Concurso.
        vals={k:round(sum(v[k] for v in complete),2) if complete else None for k in required}
        partial_total=round(sum(vals[k] for k in required),2) if complete else None
        # A classificação provisória é calculada com as avaliações completas já recebidas,
        # sem exigir que todos os avaliadores cadastrados tenham enviado notas.
        final= evaluator_count>0 and len(complete)>=evaluator_count
        status=("Final" if final else ("Parcial" if complete else "Aguardando notas"))
        output.append({"id":c["id"],"category":c["category"],"name":c["name"],"artistic_name":c.get("artistic_name") or "","photo":c.get("photo") or "",
            "aesthetics_sympathy":vals.get("aesthetics_sympathy"),"communication_elegance":vals.get("communication_elegance"),
            "samba":vals.get("samba"),"total":partial_total,"partial_total":partial_total,
            "complete_evaluators":len(complete),"expected_evaluators":evaluator_count,
            "complete":final,"status":status,
            "audition_total":c["audition_total"],"title":None})
    # Classifica provisoriamente com qualquer nota completa disponível; o título é atualizado
    # automaticamente conforme novas avaliações chegam. Desempate pelo Samba no Pé acumulado.
    for cat in ("Passista de Ouro","Diva do Samba (Plus Size)","Rainha do Samba"):
        group=[x for x in output if x["category"].strip().casefold()==cat.casefold() and x["complete_evaluators"]>0]
        group.sort(key=lambda x:(-x["total"],-(x["samba"] or 0),x["name"].casefold()))
        for i,x in enumerate(group,1):
            if cat=="Rainha do Samba": x["title"]={1:"Rainha do Carnaval",2:"Primeira Princesa",3:"Segunda Princesa"}.get(i,f"{i}º lugar")
            elif cat=="Diva do Samba (Plus Size)": x["title"]="Diva do Samba (Plus Size)" if i==1 else f"{i}º lugar"
            else: x["title"]={1:"Passista de Ouro",2:"Passista de Prata"}.get(i,f"{i}º lugar")
    output.sort(key=lambda x:(x["category"].casefold(),x["title"] is None,x["title"] or "",x["name"].casefold()))
    return output

def agulha_result_rows(contest_con, agulha_con):
    candidates=[c for c in contest_participant_rows(contest_con)
        if c["category"].strip().casefold() in ("rainha do samba","diva do samba (plus size)")]
    evaluators=[r["evaluator"] for r in agulha_con.execute(
        "SELECT evaluator FROM evaluator_roster ORDER BY position").fetchall()]
    rows=agulha_con.execute("SELECT candidate_id,evaluator,score FROM agulha_scores").fetchall()
    by={}
    for r in rows: by.setdefault(r["candidate_id"],{})[r["evaluator"]]=r["score"]
    output=[]
    for c in candidates:
        vals=by.get(c["id"],{})
        total=round(sum(vals.values()),1) if vals else None
        complete=sum(1 for ev in evaluators if ev in vals)
        output.append({"id":c["id"],"category":c["category"],"name":c["name"],
            "artistic_name":c.get("artistic_name") or "","photo":c.get("photo") or "",
            "scores":{ev:vals.get(ev) for ev in evaluators},"total":total,
            "complete_evaluators":complete,"expected_evaluators":len(evaluators),
            "complete":bool(evaluators) and complete==len(evaluators),
            "status":"Completa" if evaluators and complete==len(evaluators) else ("Parcial" if complete else "Aguardando notas")})
    # A classificação é única para as candidatas elegíveis das duas categorias.
    # Notas parciais entram no total provisório; a liberação exige todas completas.
    group=[x for x in output if x["total"] is not None]
    group.sort(key=lambda x:(-x["total"],x["name"].casefold(),x["category"].casefold()))
    position=0; previous=None
    for i,item in enumerate(group,1):
        if previous is None or item["total"] != previous: position=i
        item["position"]=position
        previous=item["total"]
    top_score=group[0]["total"] if group else None
    top_count=sum(1 for item in group if item["total"]==top_score) if group else 0
    for item in group:
        item["tied_for_first"]=item["total"]==top_score and top_count>1
    output.sort(key=lambda x:(x.get("position",999),x["category"].casefold(),x["name"].casefold()))
    return evaluators,output

def agulha_release_valid(evaluators,results):
    if not evaluators or not results or any(not item["complete"] for item in results):
        return False
    if any(item.get("tied_for_first") for item in results):
        return False
    return sum(1 for item in results
        if item.get("position")==1 and item["complete"])==1

def ensure_agulha_publication_version(con):
    """Revoga uma publicação legada por categoria na primeira leitura do ranking geral."""
    version=con.execute("SELECT setting_value FROM app_settings WHERE setting_key='publication_mode'").fetchone()
    if version is None:
        con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('publication_mode','general-v1')")
        con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('released','0') "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")

def backup_database(database,reason="pre_import",stamp=None):
    """Create a consistent SQLite snapshot in the local database backup folder."""
    if not database.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp=stamp or datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")
    destination=BACKUP_DIR/(database.stem+"_"+reason+"_"+stamp+".db")
    try:
        with sqlite3.connect(database,timeout=15) as source, sqlite3.connect(destination) as target:
            source.backup(target)
            integrity=target.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity!="ok": raise sqlite3.DatabaseError("A cópia não passou na verificação de integridade.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination

def backup_all_databases(reason="limpeza_total",protected=()):
    """Back up all application databases as one named and restorable set."""
    BACKUP_DIR.mkdir(exist_ok=True)
    missing=[database.name for database in DATABASES if not database.is_file()]
    if missing:
        raise FileNotFoundError("Banco(s) não encontrado(s): "+", ".join(missing))
    stamp=datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")
    files={}
    temporary=None
    try:
        for database in DATABASES:
            backup=backup_database(database,reason,stamp)
            if backup is None:
                raise FileNotFoundError("Não foi possível criar backup de "+database.name)
            files[database.name]=backup.name
        created_at=datetime.now().astimezone().isoformat(timespec="seconds")
        manifest={"id":stamp,"created_at":created_at,"reason":reason,"files":files}
        manifest_path=BACKUP_DIR/("backup_set_"+stamp+".json")
        temporary=manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
        os.replace(temporary,manifest_path)
    except Exception:
        for filename in files.values():
            (BACKUP_DIR/filename).unlink(missing_ok=True)
        if temporary is not None: temporary.unlink(missing_ok=True)
        raise
    prune_backup_sets(protected=protected)
    return manifest

def valid_backup_set_id(value):
    return (isinstance(value,str) and len(value)==26 and value[4]=="-" and value[7]=="-"
        and value[10]=="_" and value[13]=="-" and value[16]=="-" and value[19]=="_"
        and value[:4].isdigit() and value[5:7].isdigit() and value[8:10].isdigit()
        and value[11:13].isdigit() and value[14:16].isdigit() and value[17:19].isdigit()
        and value[20:].isdigit())

def read_backup_set(set_id):
    if not valid_backup_set_id(set_id):
        raise ValueError("Identificador do backup inválido.")
    manifest_path=BACKUP_DIR/("backup_set_"+set_id+".json")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest,dict) or manifest.get("id")!=set_id or not isinstance(manifest.get("files"),dict) or set(manifest["files"])!={database.name for database in DATABASES}:
        raise ValueError("O conjunto não contém os três bancos esperados.")
    for database in DATABASES:
        filename=manifest["files"][database.name]
        if not isinstance(filename,str) or not filename.startswith(database.stem+"_") or not filename.endswith(".db"):
            raise ValueError("O arquivo não corresponde ao banco esperado: "+database.name)
        candidate=(BACKUP_DIR/filename).resolve()
        if Path(filename).name!=filename or candidate.parent!=BACKUP_DIR.resolve() or not candidate.is_file():
            raise FileNotFoundError("Arquivo de backup ausente ou inválido: "+str(filename))
    return manifest

def list_backup_sets():
    if not BACKUP_DIR.is_dir(): return []
    sets=[]
    for manifest_path in BACKUP_DIR.glob("backup_set_*.json"):
        set_id=manifest_path.stem.removeprefix("backup_set_")
        try:
            manifest=read_backup_set(set_id)
            size=sum((BACKUP_DIR/name).stat().st_size for name in manifest["files"].values())
            sets.append({"id":set_id,"created_at":manifest.get("created_at"),"reason":manifest.get("reason","backup"),"size_bytes":size})
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            continue
    return sorted(sets,key=lambda item:(item.get("created_at") or "",item["id"]),reverse=True)

def prune_backup_sets(protected=()):
    """Keep the most recent complete sets, plus any set being restored."""
    available=list_backup_sets()
    keep=set(protected)
    for item in available:
        if item["id"] in keep: continue
        if len(keep)>=BACKUP_SET_RETENTION: break
        keep.add(item["id"])
    for item in available:
        if item["id"] in keep: continue
        try:
            manifest=read_backup_set(item["id"])
            for filename in manifest["files"].values():
                (BACKUP_DIR/filename).unlink(missing_ok=True)
            (BACKUP_DIR/("backup_set_"+item["id"]+".json")).unlink(missing_ok=True)
        except (OSError,ValueError,TypeError,json.JSONDecodeError):
            continue

def restore_database_snapshot(source_path,database):
    with sqlite3.connect(source_path,timeout=30) as source, sqlite3.connect(database,timeout=30) as target:
        integrity=source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok": raise sqlite3.DatabaseError("Backup inválido: "+str(source_path.name))
        source.backup(target)
        integrity=target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok": raise sqlite3.DatabaseError("Restauração inválida para "+database.name)

def restore_backup_set(set_id):
    manifest=read_backup_set(set_id)
    for database in DATABASES:
        with sqlite3.connect(BACKUP_DIR/manifest["files"][database.name],timeout=30) as source:
            if source.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise sqlite3.DatabaseError("Backup inválido: "+manifest["files"][database.name])
    current=backup_all_databases("antes_restauracao",protected=(set_id,))
    try:
        for database in DATABASES:
            restore_database_snapshot(BACKUP_DIR/manifest["files"][database.name],database)
    except Exception as restore_error:
        rollback_errors=[]
        for database in DATABASES:
            try:
                restore_database_snapshot(BACKUP_DIR/current["files"][database.name],database)
            except Exception as rollback_error:
                rollback_errors.append(database.name+": "+str(rollback_error))
        if rollback_errors:
            raise RuntimeError("Falha na restauração e na recuperação do estado anterior. Backup de recuperação "+current["id"]+"; erros: "+"; ".join(rollback_errors)) from restore_error
        raise RuntimeError("Restauração cancelada; o estado anterior foi recuperado. Backup de recuperação: "+current["id"]+". Detalhe: "+str(restore_error)) from restore_error
    return {"restored_set_id":set_id,"recovery_set_id":current["id"]}

def clear_all_database_data():
    """Clear every user table across the three databases in one SQLite transaction."""
    con=sqlite3.connect(AUDITION_DB,timeout=30)
    con.row_factory=sqlite3.Row
    try:
        con.execute("ATTACH DATABASE ? AS contest",(str(CONTEST_DB),))
        con.execute("ATTACH DATABASE ? AS agulha",(str(AGULHA_DB),))
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("BEGIN IMMEDIATE")
        deleted={}
        for schema in ("main","contest","agulha"):
            tables=[row[0] for row in con.execute(
                f"SELECT name FROM {schema}.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()]
            for table in tables:
                quoted='"'+table.replace('"','""')+'"'
                qualified=f'{schema}.{quoted}'
                deleted[f"{schema}.{table}"]=con.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()[0]
                con.execute(f"DELETE FROM {qualified}")
            has_sequence=con.execute(
                f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name='sqlite_sequence'"
            ).fetchone()
            if has_sequence:
                con.execute(f"DELETE FROM {schema}.sqlite_sequence")
        con.commit()
        return deleted
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*a,**kw): super().__init__(*a,directory=str(HERE),**kw)
    def _enter_api_request(self):
        global ACTIVE_API_REQUESTS
        with API_CONDITION:
            while DATABASE_MAINTENANCE: API_CONDITION.wait()
            ACTIVE_API_REQUESTS+=1
            self._maintenance_released=False
    def _leave_api_request(self):
        global ACTIVE_API_REQUESTS
        if getattr(self,"_maintenance_released",False): return
        with API_CONDITION:
            ACTIVE_API_REQUESTS=max(0,ACTIVE_API_REQUESTS-1)
            API_CONDITION.notify_all()
    def _begin_database_maintenance(self):
        global ACTIVE_API_REQUESTS,DATABASE_MAINTENANCE
        with API_CONDITION:
            ACTIVE_API_REQUESTS=max(0,ACTIVE_API_REQUESTS-1)
            self._maintenance_released=True
            while DATABASE_MAINTENANCE: API_CONDITION.wait()
            DATABASE_MAINTENANCE=True
            while ACTIVE_API_REQUESTS: API_CONDITION.wait()
    def _end_database_maintenance(self):
        global DATABASE_MAINTENANCE
        with API_CONDITION:
            DATABASE_MAINTENANCE=False
            API_CONDITION.notify_all()
    def translate_path(self,path):
        """Serve only application pages and local assets, never databases or source files."""
        route=unquote(urlparse(path).path).lstrip("/")
        if not route:
            route="central.html"
        candidate=(HERE/route).resolve()
        try:
            relative=candidate.relative_to(HERE).as_posix()
        except ValueError:
            return str(HERE/"__resource_not_found__")
        allowed_pages={"agulha.html","apresentador.html","avaliador.html","central.html","chegada.html","login.html","resultados.html"}
        allowed_asset=(relative.startswith("assets/css/") and candidate.suffix.lower()==".css") or (relative.startswith("assets/js/") and candidate.suffix.lower()==".js") or (relative=="assets/img/logo-uesp.png" and candidate.suffix.lower()==".png")
        if relative not in allowed_pages and not allowed_asset:
            return str(HERE/"__resource_not_found__")
        return str(candidate)
    def end_headers(self):
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","DENY")
        self.send_header("Referrer-Policy","same-origin")
        self.send_header("Permissions-Policy","camera=(), microphone=(), geolocation=()")
        super().end_headers()
    def request_has_same_origin(self):
        origin=self.headers.get("Origin")
        if not origin:
            return False
        try:
            return urlsplit(origin).netloc.casefold()==self.headers.get("Host","").casefold()
        except ValueError:
            return False
    def is_authenticated(self):
        cookie=SimpleCookie()
        try: cookie.load(self.headers.get("Cookie",""))
        except Exception: return False
        session=cookie.get("uesp_session")
        if not session: return False
        expires=SESSIONS.get(session.value)
        if expires is None: return False
        if expires<=time.monotonic():
            SESSIONS.pop(session.value,None)
            return False
        return True
    def send_json(self,data,status=200,extra_headers=()):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store")
        for name,value in extra_headers: self.send_header(name,value)
        self.end_headers();self.wfile.write(body)
    def read_json(self):
        length=int(self.headers.get("content-length","0"))
        if length<0 or length>9*1024*1024: raise ValueError("Requisição muito grande.")
        return json.loads(self.rfile.read(length).decode("utf-8"))
    def do_GET(self):
        self._enter_api_request()
        try: return self._do_GET()
        finally: self._leave_api_request()
    def _do_GET(self):
        path=urlparse(self.path).path
        if path not in ("/login.html","/api/health") and not self.is_authenticated():
            if path.startswith("/api/"): return self.send_json({"ok":False,"error":"Acesso não autenticado. Entre com o código do servidor."},401)
            self.send_response(303);self.send_header("Location","/login.html");self.end_headers();return
        if path=="/api/health": return self.send_json({"ok":True,"service":"UESP 2027"})
        if path=="/api/backups":
            return self.send_json({"ok":True,"sets":list_backup_sets(),"retention":BACKUP_SET_RETENTION})
        if path=="/api/active-stage":
            with dbconn(AUDITION_DB) as con:
                row=con.execute("SELECT setting_value FROM app_settings WHERE setting_key='active_stage'").fetchone()
            return self.send_json({"ok":True,"stage":row["setting_value"] if row else "AUDICAO"})
        if path=="/api/evaluator-sync-status":
            now=time.time()
            with SCORE_SYNC_REPORTS_LOCK:
                for device_id,report in list(SCORE_SYNC_REPORTS.items()):
                    retention=24*60*60 if report["pending_total"] else 90
                    if now-report["last_seen"]>retention: SCORE_SYNC_REPORTS.pop(device_id,None)
                reports=[dict(report) for report in SCORE_SYNC_REPORTS.values() if report["pending_total"]]
            reports.sort(key=lambda report:(report["stage"],report["evaluator"].casefold(),report["device"]))
            return self.send_json({"ok":True,"reports":reports,"observed_at":now})
        if path=="/api/evaluators":
            from urllib.parse import parse_qs
            stage=(parse_qs(urlparse(self.path).query).get("stage",["AUDICAO"])[0] or "AUDICAO").upper()
            if stage not in ("AUDICAO","CONCURSO"):
                return self.send_json({"ok":False,"error":"Etapa inválida."},400)
            database=CONTEST_DB if stage=="CONCURSO" else AUDITION_DB
            with dbconn(database) as con:
                rows=con.execute("SELECT evaluator FROM evaluator_roster WHERE stage=? ORDER BY position",(stage,)).fetchall()
                # Migração compatível: se a lista da Audição ainda não estiver no
                # banco novo, recupera apenas os nomes do banco legado, sem alterar
                # nem apagar o arquivo original. O Concurso permanece independente.
                if not rows and stage=="AUDICAO":
                    legacy=HERE/"uesp_2027.db"
                    if legacy.exists() and legacy.resolve() not in (AUDITION_DB.resolve(),CONTEST_DB.resolve()):
                        try:
                            with sqlite3.connect(legacy,timeout=5) as old_con:
                                exists=old_con.execute(
                                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evaluator_roster'"
                                ).fetchone()
                                if exists:
                                    old_rows=old_con.execute(
                                        "SELECT evaluator FROM evaluator_roster WHERE stage='AUDICAO' ORDER BY position"
                                    ).fetchall()
                                    names=[]; seen=set()
                                    for old_row in old_rows:
                                        name=" ".join(str(old_row[0] or "").split())
                                        key=name.casefold()
                                        if name and key not in seen:
                                            names.append(name); seen.add(key)
                                    if names:
                                        con.executemany(
                                            "INSERT OR IGNORE INTO evaluator_roster(stage,position,evaluator) VALUES('AUDICAO',?,?)",
                                            [(i,name) for i,name in enumerate(names,1)]
                                        )
                                        con.commit()
                                        rows=con.execute(
                                            "SELECT evaluator FROM evaluator_roster WHERE stage=? ORDER BY position",
                                            (stage,)
                                        ).fetchall()
                        except sqlite3.Error:
                            # A falha na leitura do banco legado não deve derrubar a API.
                            pass
            return self.send_json({"ok":True,"stage":stage,"evaluators":[r["evaluator"] for r in rows]})
        if path=="/api/arrival-candidates":
            with dbconn(CONTEST_DB) as con: candidates=contest_participant_rows(con)
            if not candidates:
                with dbconn(AUDITION_DB) as con: candidates=contest_eligible(con)
            return self.send_json({"ok":True,"candidates":candidates})
        if path=="/api/contest-report-data":
            with dbconn(CONTEST_DB) as contest_con:
                candidates=contest_participant_rows(contest_con)
                rows=contest_con.execute("SELECT candidate_id,evaluator,aesthetics_sympathy,communication_elegance,samba,updated_at FROM contest_scores").fetchall()
            scores={}
            for r in rows:
                scores.setdefault(str(r["candidate_id"]),{})[r["evaluator"]]={"aesthetics_sympathy":r["aesthetics_sympathy"],"communication_elegance":r["communication_elegance"],"samba":r["samba"],"updated_at":r["updated_at"]}
            return self.send_json({"ok":True,"candidates":candidates,"scores":scores})
        if path=="/api/candidates":
            with dbconn() as con:
                rows=con.execute("""SELECT id,category,name,photo,artistic_name,mannequin,shoe_size,body_size
                    FROM candidates ORDER BY category,name COLLATE NOCASE""").fetchall()
            return self.send_json({"ok":True,"candidates":[dict(x) for x in rows]})
        if path=="/api/arrivals":
            from urllib.parse import parse_qs
            requested_stage=(parse_qs(urlparse(self.path).query).get("stage",[""])[0] or "").strip().upper()
            if requested_stage not in ("","AUDICAO","CONCURSO"):
                return self.send_json({"ok":False,"error":"Etapa inválida para carregar chegadas."},400)
            if requested_stage=="AUDICAO":
                with dbconn(AUDITION_DB) as con: rows=con.execute("SELECT candidate_id,arrived_at,device FROM arrivals").fetchall()
                return self.send_json({"ok":True,"stage":"AUDICAO","arrivals":{str(r["candidate_id"]):{"arrived_at":r["arrived_at"],"device":r["device"],"status":"PRESENTE"} for r in rows}})
            with dbconn(CONTEST_DB) as con:
                ensure_contest_schema(con)
                migrated=con.execute("SELECT COUNT(*) FROM contest_participants").fetchone()[0]
                rows=con.execute("SELECT candidate_id,arrived_at,device,status FROM contest_arrivals").fetchall()
            if migrated: return self.send_json({"ok":True,"stage":"CONCURSO","arrivals":{str(r["candidate_id"]):{"arrived_at":r["arrived_at"],"device":r["device"],"status":r["status"]} for r in rows}})
            with dbconn() as con: rows=con.execute("SELECT candidate_id,arrived_at,device FROM arrivals").fetchall()
            return self.send_json({"ok":True,"stage":"AUDICAO","arrivals":{str(r["candidate_id"]):{"arrived_at":r["arrived_at"],"device":r["device"],"status":"PRESENTE"} for r in rows}})
        if path=="/api/scores":
            with dbconn() as con:
                rows=con.execute("SELECT candidate_id,evaluator,communication,samba,updated_at FROM scores").fetchall()
            scores={}
            for r in rows: scores.setdefault(str(r["candidate_id"]),{})[r["evaluator"]]={"communication":r["communication"],"samba":r["samba"],"updated_at":r["updated_at"]}
            return self.send_json({"ok":True,"scores":scores})
        if path=="/api/contest-candidates":
            with dbconn(CONTEST_DB) as contest_con:
                candidates=contest_participant_rows(contest_con)
                rs=contest_con.execute("SELECT candidate_id,evaluator,aesthetics_sympathy,communication_elegance,samba,updated_at FROM contest_scores").fetchall()
            saved={}
            for r in rs:
                saved.setdefault(str(r["candidate_id"]),{})[r["evaluator"]]={"aesthetics_sympathy":r["aesthetics_sympathy"],"communication_elegance":r["communication_elegance"],"samba":r["samba"],"updated_at":r["updated_at"]}
            return self.send_json({"ok":True,"candidates":candidates,"scores":saved})
        if path=="/api/export-xlsx":
            try:
                import openpyxl
                from openpyxl.styles import Font, PatternFill
                wb=openpyxl.Workbook()
                ws=wb.active; ws.title="Chegadas"
                ws.append(["Categoria","Participante","Chegada","Dispositivo","Status"])
                with dbconn(AUDITION_DB) as con:
                    rows=con.execute("""SELECT c.category,c.name,a.arrived_at,a.device
                        FROM candidates c LEFT JOIN arrivals a ON a.candidate_id=c.id
                        ORDER BY c.category,c.name COLLATE NOCASE""").fetchall()
                for r in rows:
                    ws.append([r["category"],r["name"],r["arrived_at"] or "",r["device"] or "", "PRESENTE" if r["arrived_at"] else "PENDENTE"])
                for cell in ws[1]:
                    cell.font=Font(bold=True,color="FFFFFF");cell.fill=PatternFill("solid",fgColor="C8102E")
                ws.freeze_panes="A2";ws.auto_filter.ref=ws.dimensions
                for col in ws.columns:
                    letter=col[0].column_letter
                    ws.column_dimensions[letter].width=min(42,max(14,max(len(str(cell.value or "")) for cell in col)+2))
                out=io.BytesIO();wb.save(out);wb.close();body=out.getvalue()
                self.send_response(200);self.send_header("Content-Type","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition",'attachment; filename="controle_chegadas_uesp.xlsx"')
                self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body);return
            except ImportError:
                return self.send_json({"ok":False,"error":"Falta openpyxl. Execute python -m pip install openpyxl."},500)
            except Exception as e:
                return self.send_json({"ok":False,"error":"Não foi possível exportar o Excel: "+str(e)},500)
        if path=="/api/contest-results":
            with dbconn(CONTEST_DB) as contest_con: results=contest_result_rows(None,contest_con)
            return self.send_json({"ok":True,"results":results})
        if path=="/api/presenter-data":
            with dbconn(CONTEST_DB) as contest_con:
                participants=contest_participant_rows(contest_con)
                setting=contest_con.execute("SELECT setting_value FROM app_settings WHERE setting_key='presenter_results_released'").fetchone()
                released=bool(setting and setting["setting_value"]=="1")
                payload={"ok":True,"released":released,"participants":[{"id":p["id"],"category":p["category"],"name":p["name"],"artistic_name":p.get("artistic_name") or ""} for p in participants]}
                if released:
                    final=contest_result_rows(None,contest_con)
                    winners=[]
                    wanted={"rainha do samba":{"Rainha do Carnaval":"Rainha","Primeira Princesa":"1ª Princesa","Segunda Princesa":"2ª Princesa"},"diva do samba (plus size)":{"Diva do Samba (Plus Size)":"Diva do Samba (Plus Size)"},"passista de ouro":{"Passista de Ouro":"Passista de ouro","Passista de Prata":"Passista de prata"}}
                    for item in final:
                        title=item.get("title")
                        label=wanted.get(item["category"].strip().casefold(),{}).get(title)
                        if label:
                            winners.append({"id":item["id"],"category":item["category"],"name":item["name"],"artistic_name":item.get("artistic_name") or "","photo":item.get("photo") or "","position":label})
                    payload["winners"]=winners
            return self.send_json(payload)
        if path=="/api/agulha/data":
            with dbconn(CONTEST_DB) as contest_con, dbconn(AGULHA_DB) as agulha_con:
                evaluators,results=agulha_result_rows(contest_con,agulha_con)
                ensure_agulha_publication_version(agulha_con)
                setting=agulha_con.execute("SELECT setting_value FROM app_settings WHERE setting_key='released'").fetchone()
                agulha_con.commit()
            released=bool(setting and setting["setting_value"]=="1") and agulha_release_valid(evaluators,results)
            return self.send_json({"ok":True,"evaluators":evaluators,"results":results,"released":released})
        if path=="/api/agulha/presenter-data":
            with dbconn(CONTEST_DB) as contest_con, dbconn(AGULHA_DB) as agulha_con:
                evaluators,results=agulha_result_rows(contest_con,agulha_con)
                ensure_agulha_publication_version(agulha_con)
                setting=agulha_con.execute("SELECT setting_value FROM app_settings WHERE setting_key='released'").fetchone()
                released=bool(setting and setting["setting_value"]=="1") and agulha_release_valid(evaluators,results)
                winners=[]
                if released:
                    group=[x for x in results if x.get("position")==1 and x["complete"]]
                    if len(group)==1:
                        x=group[0]
                        winners.append({"id":x["id"],"category":x["category"],"name":x["name"],
                            "artistic_name":x["artistic_name"],"photo":x["photo"],"position":"Agulha de Ouro"})
            return self.send_json({"ok":True,"released":released,"winners":winners})
        if path=="/api/results":
            with dbconn() as con:
                cs=con.execute("""
                    SELECT c.id,c.category,c.name
                    FROM candidates c
                    INNER JOIN arrivals a ON a.candidate_id=c.id
                    ORDER BY c.category,c.name COLLATE NOCASE
                """).fetchall()
                rs=con.execute("""
                    SELECT candidate_id,evaluator,communication,samba,updated_at
                    FROM scores
                """).fetchall()
            by={}
            for r in rs:
                by.setdefault(r["candidate_id"],{})[r["evaluator"]]={
                    "communication":r["communication"],
                    "samba":r["samba"],
                    "updated_at":r["updated_at"]
                }
            out=[]
            for c in cs:
                ev=by.get(c["id"],{})
                complete=[
                    v for v in ev.values()
                    if v["communication"] is not None and v["samba"] is not None
                ]
                partial_total=round(sum(v["communication"]+v["samba"] for v in complete),1)
                count=len(complete)
                out.append({
                    "id":c["id"],
                    "category":c["category"],
                    "name":c["name"],
                    "complete_evaluators":count,
                    "complete":count>=5,
                    "partial_total":partial_total if count else None,
                    "final_total":partial_total if count>=5 else None,
                    "status":"Completa" if count>=5 else ("Parcial" if count else "Aguardando notas")
                })
            return self.send_json({"ok":True,"results":out})
        return super().do_GET()
    def do_POST(self):
        self._enter_api_request()
        try: return self._do_POST()
        finally: self._leave_api_request()
    def _do_POST(self):
        path=urlparse(self.path).path
        if path!="/api/login" and not self.is_authenticated():
            return self.send_json({"ok":False,"error":"Sessão encerrada. Entre novamente com o código do servidor."},401)
        if not self.request_has_same_origin():
            return self.send_json({"ok":False,"error":"Origem da requisição inválida."},403)
        if path=="/api/login":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            pin=str(data.get("pin",""))
            if not hmac.compare_digest(pin,ACCESS_PIN):
                return self.send_json({"ok":False,"error":"Código de acesso incorreto."},401)
            now=time.monotonic()
            for old_token,expires in list(SESSIONS.items()):
                if expires<=now: SESSIONS.pop(old_token,None)
            token=secrets.token_urlsafe(32)
            SESSIONS[token]=now+8*60*60
            cookie="uesp_session="+token+"; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800"
            return self.send_json({"ok":True},extra_headers=[("Set-Cookie",cookie)])
        if path=="/api/logout":
            cookie=SimpleCookie()
            try: cookie.load(self.headers.get("Cookie",""))
            except Exception: pass
            session=cookie.get("uesp_session")
            if session: SESSIONS.pop(session.value,None)
            expired="uesp_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
            return self.send_json({"ok":True},extra_headers=[("Set-Cookie",expired)])
        if path=="/api/active-stage":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            stage=str(data.get("stage","")).strip().upper()
            if stage not in ("AUDICAO","CONCURSO"):
                return self.send_json({"ok":False,"error":"Etapa deve ser AUDICAO ou CONCURSO."},400)
            with dbconn(AUDITION_DB) as con:
                con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('active_stage',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",(stage,))
                con.commit()
            return self.send_json({"ok":True,"stage":stage})
        if path=="/api/evaluator-sync-status":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            device_id=str(data.get("device_id","")).strip()
            stage=str(data.get("stage","")).strip().upper()
            evaluator=" ".join(str(data.get("evaluator","")).split())
            pending=data.get("pending",[])
            if not device_id or len(device_id)>80 or not all(ch.isalnum() or ch in "-_" for ch in device_id):
                return self.send_json({"ok":False,"error":"Identificador do tablet inválido."},400)
            if stage not in ("AUDICAO","CONCURSO","AGULHA") or len(evaluator)>80 or not isinstance(pending,list) or len(pending)>300:
                return self.send_json({"ok":False,"error":"Etapa, avaliador ou fila inválida."},400)
            clean_pending=[]
            for item in pending:
                if not isinstance(item,dict): return self.send_json({"ok":False,"error":"Resumo de pendências inválido."},400)
                item_stage=str(item.get("stage","")).strip().upper()
                item_evaluator=" ".join(str(item.get("evaluator","")).split())
                try: count=int(item.get("count",0))
                except (TypeError,ValueError): return self.send_json({"ok":False,"error":"Quantidade pendente inválida."},400)
                if item_stage not in ("AUDICAO","CONCURSO","AGULHA") or not item_evaluator or len(item_evaluator)>80 or count<1 or count>50000:
                    return self.send_json({"ok":False,"error":"Resumo de pendências inválido."},400)
                clean_pending.append({"stage":item_stage,"evaluator":item_evaluator,"count":count})
            now=time.time()
            report={"device":"Tablet-"+device_id[-6:].upper(),"stage":stage,"evaluator":evaluator,"pending":clean_pending,"pending_total":sum(item["count"] for item in clean_pending),"last_seen":now}
            with SCORE_SYNC_REPORTS_LOCK:
                for old_id,old_report in list(SCORE_SYNC_REPORTS.items()):
                    retention=24*60*60 if old_report["pending_total"] else 90
                    if now-old_report["last_seen"]>retention: SCORE_SYNC_REPORTS.pop(old_id,None)
                if device_id not in SCORE_SYNC_REPORTS and len(SCORE_SYNC_REPORTS)>=500:
                    oldest=min(SCORE_SYNC_REPORTS,key=lambda key:SCORE_SYNC_REPORTS[key]["last_seen"])
                    SCORE_SYNC_REPORTS.pop(oldest,None)
                SCORE_SYNC_REPORTS[device_id]=report
            return self.send_json({"ok":True,"pending_total":report["pending_total"]})
        if path=="/api/evaluators":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            stage=str(data.get("stage","AUDICAO")).strip().upper()
            names=data.get("evaluators",[])
            if stage not in ("AUDICAO","CONCURSO") or not isinstance(names,list):
                return self.send_json({"ok":False,"error":"Etapa ou lista de avaliadores inválida."},400)
            cleaned=[]; seen=set()
            for value in names:
                name=" ".join(str(value or "").split())
                key=name.casefold()
                if not name: continue
                if len(name)>80: return self.send_json({"ok":False,"error":"Cada nome pode ter até 80 caracteres."},400)
                if key not in seen:
                    cleaned.append(name); seen.add(key)
            if len(cleaned)>100: return self.send_json({"ok":False,"error":"Máximo de 100 avaliadores por etapa."},400)
            database=CONTEST_DB if stage=="CONCURSO" else AUDITION_DB
            with dbconn(database) as con:
                con.execute("DELETE FROM evaluator_roster WHERE stage=?",(stage,))
                con.executemany("INSERT INTO evaluator_roster(stage,position,evaluator) VALUES(?,?,?)",[(stage,i,name) for i,name in enumerate(cleaned,1)])
                if stage=="CONCURSO":
                    con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('presenter_results_released','0') "
                        "ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")
                con.commit()
            return self.send_json({"ok":True,"stage":stage,"evaluators":cleaned,"saved":len(cleaned)})
        if path=="/api/presenter-publication":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            if not isinstance(data,dict) or not isinstance(data.get("released"),bool):
                return self.send_json({"ok":False,"error":"Informe released como verdadeiro ou falso."},400)
            with dbconn(CONTEST_DB) as con:
                con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('presenter_results_released',?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",("1" if data["released"] else "0",))
                con.commit()
            return self.send_json({"ok":True,"released":data["released"]})
        if path=="/api/clear-contest-scores":
            try:
                data=self.read_json()
            except Exception as e:
                return self.send_json({"ok":False,"error":"Confirmação inválida: "+str(e)},400)
            if not isinstance(data,dict) or data.get("confirm") is not True:
                return self.send_json({"ok":False,"error":"A exclusão exige confirmação explícita."},400)
            try:
                with dbconn(CONTEST_DB) as con:
                    deleted=con.execute("SELECT COUNT(*) FROM contest_scores").fetchone()[0]
                    con.execute("DELETE FROM contest_scores")
                    con.commit()
                return self.send_json({"ok":True,"deleted":deleted,"message":"Somente as notas do Concurso foram removidas; avaliadores e dados da Audição foram preservados."})
            except Exception as e:
                return self.send_json({"ok":False,"error":"Não foi possível limpar as notas do Concurso: "+str(e)},500)
        if path=="/api/clear-scores":
            try:
                data=self.read_json()
            except Exception as e:
                return self.send_json({"ok":False,"error":"Confirmação inválida: "+str(e)},400)
            if not isinstance(data,dict) or data.get("confirm") is not True:
                return self.send_json({"ok":False,"error":"A limpeza total exige confirmação explícita."},400)
            self._begin_database_maintenance()
            backups=None
            try:
                backups=backup_all_databases("antes_limpeza_total")
                deleted=clear_all_database_data()
                result={"ok":True,"deleted_records":sum(deleted.values()),"deleted_tables":deleted,
                    "backup_set_id":backups["id"],"backups":list(backups["files"].values()),
                    "message":"Os três bancos foram limpos e estão prontos para uma nova lista e uma nova Audição/Concurso."}
            except Exception as e:
                if backups is None:
                    result={"ok":False,"error":"Limpeza cancelada: não foi possível criar todos os backups; nenhum dado foi apagado. Detalhe: "+str(e)}
                else:
                    result={"ok":False,"error":"Falha na limpeza total. O conjunto de backup "+backups["id"]+" permanece disponível para recuperação. Detalhe: "+str(e)}
            finally:
                self._end_database_maintenance()
            return self.send_json(result,200 if result["ok"] else 500)
        if path=="/api/restore-backup":
            try:
                data=self.read_json()
            except Exception as e:
                return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            if not isinstance(data,dict) or data.get("confirm") is not True or not valid_backup_set_id(data.get("backup_set_id")):
                return self.send_json({"ok":False,"error":"Selecione um conjunto completo e confirme a restauração."},400)
            self._begin_database_maintenance()
            try:
                restored=restore_backup_set(data["backup_set_id"])
                result={"ok":True,**restored}
            except Exception as e:
                result={"ok":False,"error":str(e)}
            finally:
                self._end_database_maintenance()
            return self.send_json(result,200 if result["ok"] else 500)
        if path=="/api/publish-audition-results":
            try:
                data=self.read_json()
                participants=data.get("participants", [])
                if not isinstance(participants, list):
                    return self.send_json({"ok":False,"error":"Lista de resultados inválida."},400)
                now=datetime.now().astimezone().isoformat(timespec="seconds")
                published=[]
                with dbconn() as con:
                    for item in participants:
                        if not isinstance(item, dict):
                            continue
                        cid=item.get("candidate_id")
                        if not isinstance(cid,int):
                            continue
                        row=con.execute("SELECT id,category FROM candidates WHERE id=?",(cid,)).fetchone()
                        if not row:
                            continue
                        cat=(row["category"] or "").strip()
                        if cat.casefold() not in ("rainha do samba","diva do samba (plus size)","passista de ouro"):
                            continue
                        # Só publica participantes que tenham ao menos uma nota de Audição.
                        has_score=con.execute("SELECT 1 FROM scores WHERE candidate_id=? AND (communication IS NOT NULL OR samba IS NOT NULL) LIMIT 1",(cid,)).fetchone()
                        if not has_score:
                            continue
                        try: position=max(1,int(item.get("position",len(published)+1)))
                        except (TypeError,ValueError): position=len(published)+1
                        published.append((cid,cat,position,now))
                    con.execute("DELETE FROM audition_result_publication")
                    con.executemany("INSERT INTO audition_result_publication(candidate_id,category,position,published_at) VALUES(?,?,?,?)",published)
                    con.commit()
                with dbconn(AUDITION_DB) as audition_con, dbconn(CONTEST_DB) as contest_con: migrated=migrate_published_contest(audition_con,contest_con)
                return self.send_json({"ok":True,"published":len(published),"migrated":migrated,"published_at":now,"message":"Resultado publicado e classificados migrados para o banco independente do Concurso."})
            except Exception as e:
                return self.send_json({"ok":False,"error":"Não foi possível disponibilizar os resultados da Audição: "+str(e)},500)
        if path=="/api/agulha/evaluators":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            names=data.get("evaluators",[])
            if not isinstance(names,list): return self.send_json({"ok":False,"error":"Informe uma lista de avaliadores."},400)
            cleaned=[]; seen=set()
            for value in names:
                name=" ".join(str(value or "").split())
                if not name: continue
                if len(name)>80: return self.send_json({"ok":False,"error":"Cada nome pode ter até 80 caracteres."},400)
                if name.casefold() not in seen: cleaned.append(name); seen.add(name.casefold())
            if len(cleaned)<1: return self.send_json({"ok":False,"error":"Cadastre pelo menos um avaliador do Agulha de Ouro."},400)
            if len(cleaned)>100: return self.send_json({"ok":False,"error":"Máximo de 100 avaliadores."},400)
            with dbconn(AGULHA_DB) as con:
                con.execute("DELETE FROM evaluator_roster")
                con.executemany("INSERT INTO evaluator_roster(position,evaluator) VALUES(?,?)",[(i,n) for i,n in enumerate(cleaned,1)])
                con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('released','0') ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")
                con.commit()
            return self.send_json({"ok":True,"evaluators":cleaned})
        if path=="/api/agulha/clear":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Confirmação inválida: "+str(e)},400)
            if not isinstance(data,dict) or data.get("confirm") is not True:
                return self.send_json({"ok":False,"error":"A limpeza exige confirmação explícita."},400)
            with dbconn(AGULHA_DB) as con:
                deleted_scores=con.execute("SELECT COUNT(*) FROM agulha_scores").fetchone()[0]
                deleted_evaluators=con.execute("SELECT COUNT(*) FROM evaluator_roster").fetchone()[0]
                con.execute("DELETE FROM agulha_scores")
                con.execute("DELETE FROM evaluator_roster")
                con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('released','0') ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")
                con.commit()
            return self.send_json({"ok":True,"deleted_scores":deleted_scores,"deleted_evaluators":deleted_evaluators})
        if path=="/api/agulha/score":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            cid=data.get("candidate_id"); evaluator=" ".join(str(data.get("evaluator","")).split())
            value=data.get("score")
            if not isinstance(cid,int): return self.send_json({"ok":False,"error":"Candidata inválida."},400)
            try: score=float(value)
            except (TypeError,ValueError): return self.send_json({"ok":False,"error":"Informe nota entre 9,0 e 10,0."},400)
            if not 9<=score<=10 or abs(round(score*10)-score*10)>1e-7:
                return self.send_json({"ok":False,"error":"Notas de 9,0 a 10,0 em intervalos de 0,1."},400)
            with dbconn(CONTEST_DB) as contest_con:
                eligible={c["id"]:c for c in contest_participant_rows(contest_con)
                    if c["category"].strip().casefold() in ("rainha do samba","diva do samba (plus size)")}
            if cid not in eligible: return self.send_json({"ok":False,"error":"Participante não elegível ao Agulha de Ouro."},400)
            now=datetime.now().astimezone().isoformat(timespec="seconds")
            with dbconn(AGULHA_DB) as con:
                if not con.execute("SELECT 1 FROM evaluator_roster WHERE evaluator=?",(evaluator,)).fetchone():
                    return self.send_json({"ok":False,"error":"Avaliador não cadastrado no Agulha de Ouro."},400)
                con.execute("INSERT INTO agulha_scores(candidate_id,evaluator,score,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(candidate_id,evaluator) DO UPDATE SET score=excluded.score,updated_at=excluded.updated_at",
                    (cid,evaluator,score,now))
                con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('released','0') ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")
                con.commit()
            with dbconn(CONTEST_DB) as contest_con, dbconn(AGULHA_DB) as agulha_con:
                evaluators,results=agulha_result_rows(contest_con,agulha_con)
            return self.send_json({"ok":True,"updated_at":now,"evaluators":evaluators,"results":results})
        if path=="/api/agulha/publication":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            if not isinstance(data,dict) or not isinstance(data.get("released"),bool):
                return self.send_json({"ok":False,"error":"Informe released como verdadeiro ou falso."},400)
            with dbconn(CONTEST_DB) as contest_con, dbconn(AGULHA_DB) as agulha_con:
                ensure_agulha_publication_version(agulha_con)
                evaluators,results=agulha_result_rows(contest_con,agulha_con)
                if data["released"] and not agulha_release_valid(evaluators,results):
                    return self.send_json({"ok":False,"error":"Conclua todas as avaliações e resolva o empate geral para liberar uma única vencedora do Agulha de Ouro."},400)
                value="1" if data["released"] else "0"
                agulha_con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('released',?) "
                    "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",(value,))
                agulha_con.commit()
            return self.send_json({"ok":True,"released":data["released"]})
        if path=="/api/contest-score":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            cid=data.get("candidate_id"); evaluator=str(data.get("evaluator","")).strip()
            aesthetics=data.get("aesthetics_sympathy"); communication=data.get("communication_elegance"); samba=data.get("samba")
            if not isinstance(cid,int): return self.send_json({"ok":False,"error":"Participante inválido."},400)
            if not evaluator or len(evaluator)>80: return self.send_json({"ok":False,"error":"Informe o nome do avaliador (até 80 caracteres)."},400)
            def valid_contest(v):
                if v is None or v=="": return True
                try:
                    n=float(v); return 9<=n<=10 and abs(round(n*10)-n*10)<1e-7
                except Exception: return False
            if not all(valid_contest(v) for v in (aesthetics,communication,samba)):
                return self.send_json({"ok":False,"error":"Notas de 9,0 a 10,0 em intervalos de 0,1."},400)
            aesthetics=float(aesthetics) if aesthetics not in (None,"") else None
            communication=float(communication) if communication not in (None,"") else None
            samba=float(samba) if samba not in (None,"") else None
            with dbconn(CONTEST_DB) as contest_con:
                eligible={x["id"]:x for x in contest_participant_rows(contest_con)}
                if cid not in eligible: return self.send_json({"ok":False,"error":"Participante não está na lista migrada do Concurso."},400)
                if eligible[cid]["category"].strip().casefold()=="passista de ouro": aesthetics=None
                now=datetime.now().astimezone().isoformat(timespec="seconds")
                # Atualiza somente o critério enviado; notas de outros critérios devem ser preservadas.
                fields=[]
                values=[]
                for key,column,value in (
                    ("aesthetics_sympathy","aesthetics_sympathy",aesthetics),
                    ("communication_elegance","communication_elegance",communication),
                    ("samba","samba",samba)):
                    if key in data:
                        fields.append(column+"=excluded."+column)
                        values.append(value)
                if not fields:
                    return self.send_json({"ok":False,"error":"Nenhum critério de nota foi informado."},400)
                contest_con.execute(
                    "INSERT INTO contest_scores(candidate_id,evaluator,aesthetics_sympathy,communication_elegance,samba,updated_at) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(candidate_id,evaluator) DO UPDATE SET "
                    + ",".join(fields)+",updated_at=excluded.updated_at",
                    (cid,evaluator,aesthetics,communication,samba,now))
                contest_con.execute("INSERT INTO app_settings(setting_key,setting_value) VALUES('presenter_results_released','0') "
                    "ON CONFLICT(setting_key) DO UPDATE SET setting_value='0'")
                contest_con.commit()
            return self.send_json({"ok":True,"updated_at":now})
        if path=="/api/score":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            cid=data.get("candidate_id"); evaluator=str(data.get("evaluator","")).strip()
            communication=data.get("communication"); samba=data.get("samba")
            if not isinstance(cid,int): return self.send_json({"ok":False,"error":"Candidata inválida."},400)
            if not evaluator or len(evaluator)>80: return self.send_json({"ok":False,"error":"Informe o nome do avaliador (até 80 caracteres)."},400)
            def valid(v):
                if v is None or v=="": return True
                try:
                    n=float(v); return 9<=n<=10 and abs(round(n*10)-n*10)<1e-7
                except Exception: return False
            if not valid(communication) or not valid(samba): return self.send_json({"ok":False,"error":"Notas de 9,0 a 10,0 em intervalos de 0,1."},400)
            communication=float(communication) if communication not in (None,"") else None
            samba=float(samba) if samba not in (None,"") else None
            with dbconn() as con:
                if not con.execute("SELECT id FROM candidates WHERE id=?",(cid,)).fetchone(): return self.send_json({"ok":False,"error":"Candidata não encontrada."},404)
                now=datetime.now().astimezone().isoformat(timespec="seconds")
                con.execute("INSERT INTO scores(candidate_id,evaluator,communication,samba,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(candidate_id,evaluator) DO UPDATE SET communication=excluded.communication,samba=excluded.samba,updated_at=excluded.updated_at",(cid,evaluator,communication,samba,now)); con.commit()
            return self.send_json({"ok":True,"updated_at":now})
        if path=="/api/arrival":
            try: data=self.read_json()
            except Exception as e: return self.send_json({"ok":False,"error":"Dados inválidos: "+str(e)},400)
            cid=data.get("candidate_id")
            if not isinstance(cid,int): return self.send_json({"ok":False,"error":"Candidato inválido."},400)
            present=bool(data.get("present"))
            absent=bool(data.get("absent"))
            save_only=bool(data.get("save_only"))
            photo=data.get("photo")
            if photo is not None:
                if not isinstance(photo,str) or not photo.startswith("data:image/") or len(photo)>8*1024*1024:
                    return self.send_json({"ok":False,"error":"Foto inválida ou muito grande (máximo 8 MB)."},400)
            with dbconn(CONTEST_DB) as contest_con:
                contest_person=contest_con.execute("SELECT id FROM contest_participants WHERE id=?",(cid,)).fetchone()
            if contest_person:
                with dbconn(CONTEST_DB) as con:
                    fields=("artistic_name","mannequin","shoe_size","body_size"); assignments=[]; values=[]
                    for field in fields:
                        if field in data: assignments.append(field+"=?"); values.append(" ".join(str(data.get(field) or "").split())[:120])
                    if photo is not None: assignments.append("photo=?"); values.append(photo)
                    if assignments: con.execute("UPDATE contest_participants SET "+", ".join(assignments)+" WHERE id=?",(*values,cid))
                    if save_only:
                        con.commit(); return self.send_json({"ok":True,"saved":True,"photo_saved":photo is not None})
                    if present or absent:
                        now=datetime.now().astimezone().isoformat(timespec="seconds"); status="PRESENTE" if present else "AUSENTE"; device=data.get("device","Recepção") if present else "AUSENTE"
                        con.execute("INSERT INTO contest_arrivals(candidate_id,arrived_at,device,status) VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET arrived_at=excluded.arrived_at,device=excluded.device,status=excluded.status",(cid,now,device,status))
                        con.commit(); return self.send_json({"ok":True,"arrival":{"arrived_at":now,"device":device,"status":status}})
                    con.execute("DELETE FROM contest_arrivals WHERE candidate_id=?",(cid,)); con.commit(); return self.send_json({"ok":True,"arrival":None})
            with dbconn() as con:
                exists=con.execute("SELECT id FROM candidates WHERE id=?",(cid,)).fetchone()
                if not exists:return self.send_json({"ok":False,"error":"Candidato não encontrado."},404)
                fields=("artistic_name","mannequin","shoe_size","body_size")
                assignments=[]; values=[]
                for field in fields:
                    if field in data:
                        assignments.append(field+"=?")
                        values.append(" ".join(str(data.get(field) or "").split())[:120])
                if photo is not None:
                    assignments.append("photo=?"); values.append(photo)
                if assignments:
                    con.execute("UPDATE candidates SET "+", ".join(assignments)+" WHERE id=?",(*values,cid))
                if save_only:
                    con.commit()
                    return self.send_json({"ok":True,"saved":True,"photo_saved":photo is not None})
                if present:
                    now=datetime.now().astimezone().isoformat(timespec="seconds")
                    con.execute("INSERT INTO arrivals(candidate_id,arrived_at,device) VALUES(?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET arrived_at=excluded.arrived_at,device=excluded.device",(cid,now,data.get("device","Recepção")))
                    row=con.execute("SELECT candidate_id,arrived_at,device FROM arrivals WHERE candidate_id=?",(cid,)).fetchone()
                    con.commit()
                    return self.send_json({"ok":True,"arrival":{"arrived_at":row["arrived_at"],"device":row["device"],"status":"PRESENTE"}})
                if absent:
                    now=datetime.now().astimezone().isoformat(timespec="seconds")
                    con.execute("INSERT INTO arrivals(candidate_id,arrived_at,device) VALUES(?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET arrived_at=excluded.arrived_at,device=excluded.device",(cid,now,"AUSENTE"))
                    con.commit()
                    return self.send_json({"ok":True,"arrival":{"arrived_at":now,"device":"AUSENTE","status":"AUSENTE"}})
                con.execute("DELETE FROM arrivals WHERE candidate_id=?",(cid,));con.commit()
                return self.send_json({"ok":True,"arrival":None})
        if path!="/api/import": return self.send_json({"ok":False,"error":"Rota não encontrada"},404)
        if self.headers.get("X-Uesp-Confirm-Import")!="true":
            return self.send_json({"ok":False,"error":"Confirme a reimportação na tela da Central."},400)
        ctype=self.headers.get("content-type","")
        try:
            length=int(self.headers.get("content-length","0"))
            if length<=0 or length>50*1024*1024:return self.send_json({"ok":False,"error":"Arquivo vazio ou maior que 50 MB."},400)
            filename,raw=parse_multipart(ctype,self.rfile.read(length))
            if not raw:return self.send_json({"ok":False,"error":"Arquivo não recebido."},400)
            import openpyxl
            wb=openpyxl.load_workbook(io.BytesIO(raw),read_only=True,data_only=True);ws=wb[wb.sheetnames[0]]
            rows=[];skipped=0
            for row in ws.iter_rows(min_row=2,values_only=True):
                cat=str(row[0]).strip() if len(row)>0 and row[0] is not None else ""
                name=str(row[1]).strip() if len(row)>1 and row[1] is not None else ""
                if not cat and not name:continue
                if not cat or not name:skipped+=1;continue
                rows.append((cat,name))
            wb.close()
            if not rows:return self.send_json({"ok":False,"error":"Nenhum candidato válido nas colunas A e B."},400)
            self._begin_database_maintenance()
            try:
                backup_set=backup_all_databases("antes_reimportacao")
                with dbconn() as con:
                    # Reimportação substitui candidatos e limpa presenças antigas para evitar associação incorreta.
                    con.execute("DELETE FROM arrivals");con.execute("DELETE FROM scores");con.execute("DELETE FROM audition_result_publication");con.execute("DELETE FROM candidates")
                    con.executemany("INSERT OR IGNORE INTO candidates(category,name) VALUES (?,?)",rows);con.commit()
                    grouped=con.execute("SELECT category,COUNT(*) n FROM candidates GROUP BY category").fetchall()
                result={"ok":True,"imported":sum(x["n"] for x in grouped),"counts":{x["category"]:x["n"] for x in grouped},"skipped":skipped,"backup":backup_set["files"][AUDITION_DB.name],"backup_set_id":backup_set["id"]}
                status=200
            except Exception as e:
                result={"ok":False,"error":"Erro ao importar Excel: "+str(e)};status=400
            finally:
                self._end_database_maintenance()
            return self.send_json(result,status)
        except ImportError:return self.send_json({"ok":False,"error":"Falta openpyxl. Execute python -m pip install openpyxl"},500)
        except Exception as e:return self.send_json({"ok":False,"error":"Erro ao importar Excel: "+str(e)},400)
    def log_message(self,fmt,*args):print("%s - %s"%(self.address_string(),fmt%args))

def local_ip():
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:s.connect(("192.0.2.1",80));return s.getsockname()[0]
    except Exception:return "IP-DO-NOTEBOOK"
    finally:s.close()

def init_contest_db():
    with dbconn(CONTEST_DB) as con:
        ensure_contest_schema(con)
        con.commit()

if __name__=="__main__":
    with dbconn(AUDITION_DB): pass
    init_contest_db()
    with dbconn(AGULHA_DB): pass
    try:
        with dbconn(AUDITION_DB) as audition_con, dbconn(CONTEST_DB) as contest_con:
            if audition_con.execute("SELECT COUNT(*) FROM audition_result_publication").fetchone()[0]: migrate_published_contest(audition_con,contest_con)
    except Exception as e: print("Aviso: migração do Concurso não concluída: "+str(e))
    ip=local_ip()
    print("\nCentral UESP 2027 iniciada.")
    if ACCESS_PIN_SOURCE=="environment":
        print("Código de acesso configurado pela variável UESP_ACCESS_PIN.")
    elif ACCESS_PIN_SOURCE=="file":
        print("Código de acesso carregado de "+PIN_FILE.name+".")
    else:
        print("Código temporário de acesso (válido até encerrar o servidor): "+ACCESS_PIN)
    print("No notebook: http://127.0.0.1:8765/central.html")
    print(f"Controle de chegada: http://127.0.0.1:8765/chegada.html")
    print(f"Na rede Wi-Fi: http://{ip}:8765/central.html")
    print(f"Chegada Rainha: http://{ip}:8765/chegada.html?categoria=rainha")
    print(f"Chegada Passista: http://{ip}:8765/chegada.html?categoria=passista")
    print(f"Chegada Diva do Samba (Plus Size): http://{ip}:8765/chegada.html?categoria=diva")
    print("Mantenha esta janela aberta. Ctrl+C encerra o servidor.\n")
    ThreadingHTTPServer(("0.0.0.0",8765),Handler).serve_forever()
