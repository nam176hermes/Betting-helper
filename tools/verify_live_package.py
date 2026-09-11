"""Check the canonical Part B package boundary; not a host or live authorization."""

# ruff: noqa: E501 -- fixed JavaScript parser program, not Python expressions.

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "contracts/live_readonly/v1/package-policy.json"

# Parse emitted JavaScript without evaluating it. This supplements the behavioral
# browser/storage/protocol tests; AST inventory alone cannot qualify a live run.
AST_CHECK = r"""
const fs=require('node:fs'),ts=require(process.argv[1]);
const data=JSON.parse(fs.readFileSync(0,'utf8')), errors=[], modules=[];
const deny=(file,code)=>errors.push(file+':'+code);
const chain=n=>ts.isIdentifier(n)?n.text:ts.isPropertyAccessExpression(n)?chain(n.expression)+'.'+n.name.text:'';
const maximal=n=>{while(n.parent&&ts.isPropertyAccessExpression(n.parent)&&n.parent.expression===n)n=n.parent;return n;};
const reference=n=>!(ts.isPropertyAccessExpression(n.parent)&&n.parent.name===n)
  && !(ts.isPropertyAssignment(n.parent)&&n.parent.name===n&&!ts.isShorthandPropertyAssignment(n.parent));
const forbidden=new Set(['fetch','XMLHttpRequest','EventSource','WebTransport','Worker','SharedWorker','importScripts','eval','Function','Reflect','localStorage','sessionStorage','navigator','top','parent','opener','self']);
const carriers=new Set(['constructor','__proto__','ownerDocument','defaultView','contentWindow','contentDocument','parentWindow','view','window','document','chrome','localStorage','sessionStorage','navigator','cookie']);
// Finite member grammar for the fixed reader. An added DOM capability must be
// reviewed explicitly, including destructuring; it cannot inherit a file-wide exemption.
const readerMembers=new Set(('END_TO_END START_TO_START addEventListener addListener at bindingRevision bottom captureId catch ceil charCodeAt childElementCount childNodes classList className cloneRange commonAncestorContainer compareBoundaryPoints comparePoint disconnect display documentElement documentEpoch encode entries exactUrl fields filter from fromEntries getAttribute getBoundingClientRect getRangeAt getURL hasAttribute height href id includes isCollapsed isConnected isSafeInteger join keys leaseMs left length map max normalize now observe onMessage opacity parentElement profileHash push querySelector querySelectorAll rangeCount right runtime selectors sendMessage some sort split status stringify tab tagName test textContent then toISOString toLowerCase top trim url visibility visibilityState width').split(' '));
const directCall=n=>ts.isCallExpression(n.parent)&&n.parent.expression===n;
const globals=new Set(('AbortController Array BigInt Date Element Error Infinity JSON Map Math MutationObserver Number Object Promise Range RegExp Set String Text TextDecoder TextEncoder URL Uint8Array WebSocket addEventListener atob btoa chrome clearInterval clearTimeout crypto document getComputedStyle getSelection indexedDB innerHeight innerWidth isFinite isNaN location parseInt performance setInterval setTimeout structuredClone window').split(' '));
const computed={
 'src/canonical.js':['this.source[this.offset]'],
 'src/live/protocol.js':['clientTypes[this.role]'],
 'src/live/capture.js':['second[key+"_selection"]','second[key+"_odds"]'],
 'src/live/spool.js':['entries[Number(BigInt(state.ack)-1n)]','entries[Number(number-1n)]'],
};
const fieldNames='fixture_id,home_team,away_team,home_id,away_id,market_root,horizon_label,home_selection,draw_selection,away_selection,home_odds,draw_odds,away_odds,market_status,score,period';
for(const [file,code] of Object.entries(data.sources)){
 const source=ts.createSourceFile(file,code,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS), imports=[];
 const options={allowJs:true,noLib:true,noResolve:true},host=ts.createCompilerHost(options);
 host.getSourceFile=name=>name===file?source:undefined;
 host.fileExists=name=>name===file;host.readFile=name=>name===file?code:undefined;
 const checker=ts.createProgram([file],options,host).getTypeChecker();
 const declaration=n=>ts.isIdentifier(n)?checker.getSymbolAtLocation(n)?.valueDeclaration:undefined;
 const constant=(n,seen=new Set())=>{
  if(ts.isStringLiteral(n)||ts.isNumericLiteral(n))return n.text;
  if(ts.isParenthesizedExpression(n))return constant(n.expression,seen);
  if(ts.isBinaryExpression(n)&&n.operatorToken.kind===ts.SyntaxKind.PlusToken){
   const a=constant(n.left,seen),b=constant(n.right,seen);return a===undefined||b===undefined?undefined:a+b;
  }
  const d=declaration(n);
  if(d&&ts.isVariableDeclaration(d)&&d.initializer&&!seen.has(d)&&d.parent.flags&ts.NodeFlags.Const){
   return constant(d.initializer,new Set([...seen,d]));
  }
 };
 const initialized=(n,text)=>{const d=declaration(n);return !!d&&ts.isVariableDeclaration(d)&&d.initializer?.getText(source)===text;};
 const fieldArray=n=>{const d=declaration(n),a=d?.initializer;return !!a&&ts.isArrayLiteralExpression(a)
  &&a.elements.every(ts.isStringLiteral)&&a.elements.map(v=>v.text).join(',')===fieldNames;};
 const fieldIndex=n=>{
  const d=declaration(n),loop=d?.parent?.parent;
  return !!d&&ts.isVariableDeclaration(d)&&ts.isForOfStatement(loop)&&loop.initializer===d.parent
   &&!!(d.parent.flags&ts.NodeFlags.Const)&&fieldArray(loop.expression);
 };
 const readerIndex=n=>{
  const path=chain(n.expression),key=constant(n.argumentExpression),base=n.expression.expression;
  if(path==='global')return initialized(n.expression,'globalThis')&&key==='BH_LIVE_READER_V1';
  if(['valid','texts','nodes'].includes(path))return key==='0';
  if(path==='m')return initialized(n.expression,'message')&&['kind','operation','value'].includes(key);
  if(path==='s.selectors')return initialized(base,'structuredClone(value)')&&['selection_mode','match_root'].includes(key);
  if(path==='values'&&!initialized(n.expression,'{}'))return false;
  return ['values','scope.selectors'].includes(path)&&((key===undefined&&fieldIndex(n.argumentExpression))
   ||fieldNames.split(',').includes(key)||(path==='scope.selectors'&&key==='match_root'));
 };
 if(source.parseDiagnostics.length)deny(file,'SYNTAX');
 const reader=file===data.policy.operator_reader, ui=data.policy.extension_dom_owners.includes(file);
 const visit=n=>{
  if(ts.isImportDeclaration(n)||ts.isExportDeclaration(n)){
   if(n.moduleSpecifier){if(!ts.isStringLiteral(n.moduleSpecifier))deny(file,'IMPORT');else imports.push(n.moduleSpecifier.text);}
  }
  if(ts.isObjectBindingPattern(n)&&reader)deny(file,'OPERATOR_BINDING');
  if(ts.isBindingElement(n)&&ts.isObjectBindingPattern(n.parent)){
   const key=n.propertyName??n.name;
   if(!ts.isIdentifier(key)&&!ts.isStringLiteral(key)||carriers.has(key.text)||forbidden.has(key.text))deny(file,'CAPABILITY_BINDING');
  }
  if(ts.isCallExpression(n)&&(n.expression.kind===ts.SyntaxKind.ImportKeyword||chain(n.expression)==='require'))deny(file,'DYNAMIC_IMPORT');
  if(ts.isPropertyAccessExpression(n)||ts.isElementAccessExpression(n)){
   const member=ts.isPropertyAccessExpression(n)?n.name.text:constant(n.argumentExpression);
   if(carriers.has(member))deny(file,'INDIRECT_CAPABILITY');
   if(ts.isElementAccessExpression(n)&&!ts.isStringLiteral(n.argumentExpression)&&!ts.isNumericLiteral(n.argumentExpression)&&!ts.isIdentifier(n.argumentExpression)
      &&!(computed[file]??[]).includes(n.getText(source).replace(/\s/g,''))
      &&!(file==='src/live/background.js'&&n.getText(source)==="schema['validate'+k]"&&directCall(n)))deny(file,'COMPUTED_CAPABILITY');
   if(reader&&ts.isPropertyAccessExpression(n)&&!readerMembers.has(member))deny(file,'OPERATOR_MEMBER:'+member);
   if(reader&&ts.isElementAccessExpression(n)&&!readerIndex(n))deny(file,'OPERATOR_INDEX_BINDING');
   if(ui&&ts.isElementAccessExpression(n)&&member===undefined){
    const base=ts.isPropertyAccessExpression(n.expression)?n.expression.expression:undefined;
    const known=base&&((chain(n.expression)==='book.selections'&&initialized(base,'selectedBook(snapshot, horizon)'))
      ||(chain(n.expression)==='d.markets'&&initialized(base,'snapshot.display')));
    if(!known)deny(file,'UI_INDEX_BINDING');
   }
   if(reader&&ts.isElementAccessExpression(n)&&chain(n.expression)==='m'&&(!ts.isStringLiteral(n.argumentExpression)||!['kind','operation','value'].includes(member)))deny(file,'OPERATOR_MESSAGE_INDEX');
   if(reader&&['cookie','innerHTML','outerHTML','value','src','href','assign','replace','pushState','replaceState','click','append','appendChild','prepend','remove','removeChild','setAttribute','insertAdjacentHTML','write','writeln','setProperty','defineProperty','assign'].includes(member)
     &&chain(n)!=='location.href'&&!(member==='value'&&ts.isElementAccessExpression(n)&&chain(n.expression)==='m'))deny(file,'OPERATOR_DOM_MUTATION_OR_SECRET');
  }
  if(reader&&ts.isBinaryExpression(n)&&n.operatorToken.kind>=ts.SyntaxKind.FirstAssignment&&n.operatorToken.kind<=ts.SyntaxKind.LastAssignment
    &&!ts.isIdentifier(n.left)){
   const left=n.left.getText(source).replace(/\s/g,'').replaceAll("'",'"');
   if(!['global["BH_LIVE_READER_V1"]','values[name]','s.selectors','s.selectors["match_root"]'].includes(left))deny(file,'OPERATOR_WRITE');
   if(left==='s.selectors'&&!initialized(n.left.expression,'structuredClone(value)'))deny(file,'OPERATOR_WRITE_BINDING');
  }
  if(reader&&(ts.isDeleteExpression(n)||((ts.isPrefixUnaryExpression(n)||ts.isPostfixUnaryExpression(n))
     &&[ts.SyntaxKind.PlusPlusToken,ts.SyntaxKind.MinusMinusToken].includes(n.operator)&&!ts.isIdentifier(n.operand))
     ||((ts.isForOfStatement(n)||ts.isForInStatement(n))&&!ts.isVariableDeclarationList(n.initializer))))deny(file,'OPERATOR_WRITE');
  if((reader||ui)&&n.kind===ts.SyntaxKind.ThisKeyword)deny(file,'GLOBAL_ALIAS');
  if(ts.isIdentifier(n)&&reference(n)){
   const name=n.text, path=chain(maximal(n));
   if(!checker.getSymbolAtLocation(n)&&!globals.has(name))deny(file,'UNDECLARED_GLOBAL:'+name);
   if(forbidden.has(name))deny(file,'FORBIDDEN_GLOBAL');
   if(name==='chrome'&&!ts.isTypeOfExpression(n.parent)&&!(data.policy.chrome_owners[file]??[]).includes(path))deny(file,'CHROME_OWNER:'+path);
   if(name==='chrome'&&!ts.isTypeOfExpression(n.parent)&&path!=='chrome.runtime.id'){
    const use=maximal(n);if(!ts.isCallExpression(use.parent)||use.parent.expression!==use)deny(file,'CHROME_ALIAS');
   }
   if(name==='indexedDB'&&(file!==data.policy.indexeddb_owner||path!=='indexedDB.open'||!directCall(maximal(n))))deny(file,'STORAGE_OWNER');
   if(name==='WebSocket'){
    const call=n.parent;
    if(!data.policy.websocket_owners[file]||(!['WebSocket.OPEN','WebSocket.CLOSED','WebSocket.CLOSING','WebSocket.CONNECTING'].includes(path)
      &&(!ts.isNewExpression(call)||call.expression!==n||call.arguments?.length!==1||!ts.isStringLiteral(call.arguments[0])
      ||call.arguments[0].text!==data.policy.websocket_owners[file])))deny(file,'OUTBOUND_NETWORK');
   }
   if(name==='globalThis'&&!(reader&&ts.isVariableDeclaration(n.parent)&&n.parent.name.getText(source)==='global'))deny(file,'GLOBAL_ALIAS');
   if(reader&&name==='global'&&!initialized(n,'globalThis'))deny(file,'GLOBAL_ALIAS');
   if(reader&&fieldArray(n)&&!(ts.isVariableDeclaration(n.parent)&&n.parent.name===n)
      &&!(ts.isForOfStatement(n.parent)&&n.parent.expression===n)&&!ts.isSpreadElement(n.parent)
      &&!(path==='fields.map'&&directCall(maximal(n))))deny(file,'OPERATOR_FIELD_ALIAS');
   if(reader&&name==='global'&&!(ts.isVariableDeclaration(n.parent)&&n.parent.name===n)
      &&!(ts.isElementAccessExpression(n.parent)&&n.parent.expression===n&&ts.isStringLiteral(n.parent.argumentExpression)&&n.parent.argumentExpression.text==='BH_LIVE_READER_V1'))deny(file,'GLOBAL_ALIAS');
   if(['document','window','location','getSelection','getComputedStyle','MutationObserver','addEventListener'].includes(name)&&!reader&&!ui)deny(file,'DOM_OWNER');
   if(ui&&name==='window'&&!(path==='window.addEventListener'&&directCall(maximal(n))
      &&maximal(n).parent.arguments[0]?.getText(source)==='"pagehide"'))deny(file,'UI_WINDOW_ACCESS');
   if(ui&&name==='document'&&!['document.createElement','document.activeElement','document.querySelector','document.body.dataset'].includes(path)
      &&!ts.isTypeOfExpression(n.parent))deny(file,'UI_DOCUMENT_ACCESS');
   if(ui&&name==='location')deny(file,'NAVIGATION');
   if(reader&&name==='document'&&!['document.querySelector','document.querySelectorAll','document.visibilityState','document.documentElement','document.addEventListener'].includes(path)
      &&!(ts.isCallExpression(n.parent)&&chain(n.parent.expression)==='stableSelector'&&n.parent.arguments[1]===n))deny(file,'DOCUMENT_ACCESS');
   if(reader&&name==='location'&&path!=='location.href')deny(file,'NAVIGATION');
   if(reader&&['window'].includes(name))deny(file,'PAGE_CHANNEL');
  }
  if(ts.isCallExpression(n)){
   const path=chain(n.expression);
   if(path==='chrome.scripting.executeScript'){
    const compact=n.arguments[0]?.getText(source).replace(/\s/g,'').replaceAll("'",'"');
    if(compact!=='{target:{tabId:plan.tabId,frameIds:[0]},files:["src/live/dom_reader.js"],world:"ISOLATED"}')deny(file,'SCRIPT_TARGET');
   }
   if(reader&&['addEventListener','document.addEventListener'].includes(path)
      &&(!ts.isStringLiteral(n.arguments[0])||!['visibilitychange','pagehide','popstate','hashchange'].includes(n.arguments[0].text)))deny(file,'PAGE_CHANNEL');
  }
  ts.forEachChild(n,visit);
 };visit(source);modules.push({file,imports});
}
process.stdout.write(JSON.stringify({errors:[...new Set(errors)],modules}));
"""


def package_policy() -> dict[str, Any]:
    value = json.loads(POLICY.read_bytes())
    if (
        value["schema_version"] != "part-b-package-policy/v1"
        or value["production_authority"] != "NONE"
    ):
        raise ValueError("E_LIVE_PACKAGE_POLICY")
    return cast(dict[str, Any], value)


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.styles: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        allowed = {
            "html": {"lang"},
            "head": set(),
            "title": set(),
            "body": {"data-live-workspace"},
            "header": set(),
            "main": set(),
            "h1": set(),
            "p": {"class"},
            "details": {"class"},
            "summary": set(),
            "ol": set(),
            "li": set(),
        }
        if len(values) != len(attrs):
            raise ValueError("E_LIVE_PACKAGE_HTML")
        if tag == "script":
            if set(values) != {"src", "type"} or values["type"] != "module":
                raise ValueError("E_LIVE_PACKAGE_HTML")
            self.scripts.append(str(values["src"]))
            self.in_script = True
        elif tag == "link":
            if values != {"rel": "stylesheet", "href": "panel.css"}:
                raise ValueError("E_LIVE_PACKAGE_HTML")
            self.styles.append("panel.css")
        elif tag == "meta":
            if values not in (
                {"charset": "utf-8"},
                {"name": "viewport", "content": "width=device-width,initial-scale=1"},
            ):
                raise ValueError("E_LIVE_PACKAGE_HTML")
        elif tag not in allowed or set(values) - allowed[tag]:
            raise ValueError("E_LIVE_PACKAGE_HTML")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script and data.strip():
            raise ValueError("E_LIVE_PACKAGE_HTML")


def verify_live_package(directory: Path) -> dict[str, Any]:
    policy = package_policy()
    expected = {
        "manifest.json",
        *policy["assets"],
        *policy["generated_modules"],
        *("src/" + name for name in policy["shared_modules"]),
        *("src/live/" + name + ".js" for name in policy["live_modules"]),
    }
    if directory.resolve() != directory or not directory.is_dir():
        raise ValueError("E_LIVE_PACKAGE_PATH")
    files = {}
    for path in directory.rglob("*"):
        if path.resolve() != path or not (path.is_dir() or path.is_file()):
            raise ValueError("E_LIVE_PACKAGE_PATH")
        if path.is_file():
            if path.stat().st_nlink != 1 or path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("E_LIVE_PACKAGE_PATH")
            files[path.relative_to(directory).as_posix()] = path.read_bytes()
    if set(files) != expected:
        raise ValueError("E_LIVE_PACKAGE_INVENTORY")
    manifest = json.loads(files["manifest.json"])
    identity = {"name", "version", "description", "key"}
    if (
        set(manifest) != set(policy["manifest"]) | identity
        or any(manifest[name] != value for name, value in policy["manifest"].items())
        or manifest != json.loads((ROOT / "extension/manifest.live.json").read_bytes())
    ):
        raise ValueError("E_LIVE_PACKAGE_MANIFEST")
    for name in ("src/live/panel.html", "src/live/workspace.html"):
        page = Page()
        page.feed(files[name].decode())
        if page.scripts != ["workspace.js"] or page.styles != ["panel.css"]:
            raise ValueError("E_LIVE_PACKAGE_HTML")
    css = files["src/live/panel.css"].decode().lower()
    if "url(" in css or "@import" in css:
        raise ValueError("E_LIVE_PACKAGE_CSS")
    node = shutil.which("node")
    if not node:
        raise ValueError("E_LIVE_PACKAGE_NODE")
    result = subprocess.run(  # noqa: S603 -- fixed parser, emitted code is parsed, never executed.
        [node, "-e", AST_CHECK, str(ROOT / "extension/node_modules/typescript")],
        input=json.dumps(
            {
                "sources": {k: v.decode() for k, v in files.items() if k.endswith(".js")},
                "policy": policy,
            }
        ),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    observed = json.loads(result.stdout)
    if observed["errors"]:
        raise ValueError("E_LIVE_PACKAGE_CAPABILITY:" + ",".join(observed["errors"]))
    for module in observed["modules"]:
        for imported in module["imports"]:
            if (
                not imported.startswith(".")
                or "\\" in imported
                or "?" in imported
                or "#" in imported
            ):
                raise ValueError("E_LIVE_PACKAGE_IMPORT")
            target = (directory / PurePosixPath(module["file"]).parent / imported).resolve()
            if (
                not target.is_relative_to(directory)
                or target.relative_to(directory).as_posix() not in expected
            ):
                raise ValueError("E_LIVE_PACKAGE_IMPORT")
    return {
        "schema_version": "part-b-package-boundary/v1",
        "result": "PASS",
        "scope": "STATIC_PACKAGE_BOUNDARY_ONLY",
        "production_authority": "NONE",
        "independent_review": "NOT_INFERRED",
        "policy_sha256": hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())},
    }
