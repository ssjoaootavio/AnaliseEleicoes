/**
 * Recebe opiniões, dúvidas e insights enviados pela página de stories
 * (stories/index.html) e grava uma linha por envio na aba "Respostas".
 *
 * Como publicar (uma vez):
 *  1. Crie uma planilha nova (sheets.new) e dê um nome, por exemplo "Feedback Eleições 2026".
 *  2. Menu Extensões > Apps Script. Apague o conteúdo e cole este arquivo inteiro. Salve.
 *     (Também funciona como script avulso em script.google.com: aí ele cria a planilha
 *     "Feedback Eleições 2026" no seu Drive no primeiro envio. Rode mostrarPlanilha() para ver o link.)
 *  3. Implantar > Nova implantação > tipo "App da Web".
 *     Executar como: Eu. Quem pode acessar: Qualquer pessoa. Implantar e autorizar.
 *  4. Copie a URL que termina em /exec e coloque em ENDPOINT no stories/index.html.
 *
 * Para baixar: na planilha, Arquivo > Fazer download > CSV.
 */
const ABA = 'Respostas';
const TIPOS = ['Opinião', 'Dúvida', 'Insight'];
const MAX_TEXTO = 2000;

function doPost(e) {
  const p = (e && e.parameter) || {};
  const texto = String(p.texto || '').trim().slice(0, MAX_TEXTO);
  // "site" é um campo invisível na página: se vier preenchido, é robô.
  if (!texto || p.site) return resposta({ ok: false });

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const ss = planilha();
    const aba = ss.getSheetByName(ABA) || ss.insertSheet(ABA);
    if (aba.getLastRow() === 0) {
      aba.appendRow(['DATA_HORA', 'TIPO', 'TEXTO', 'STORY', 'PAGINA']);
      aba.setFrozenRows(1);
    }
    aba.appendRow([
      new Date(),
      TIPOS.indexOf(p.tipo) >= 0 ? p.tipo : 'Sem tipo',
      semFormula(texto),
      String(p.story || '').slice(0, 10),
      String(p.pagina || '').slice(0, 200),
    ]);
  } finally {
    lock.releaseLock();
  }
  return resposta({ ok: true });
}

// Usa a planilha ligada ao script; se o script for avulso (criado em script.google.com),
// cria a planilha "Feedback Eleições 2026" no seu Drive na primeira vez e guarda o ID.
function planilha() {
  const ativa = SpreadsheetApp.getActiveSpreadsheet();
  if (ativa) return ativa;
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('PLANILHA_ID');
  if (id) return SpreadsheetApp.openById(id);
  const nova = SpreadsheetApp.create('Feedback Eleições 2026');
  props.setProperty('PLANILHA_ID', nova.getId());
  return nova;
}

// Rode esta função no editor para ver no registro (log) o link da planilha.
function mostrarPlanilha() {
  Logger.log(planilha().getUrl());
}

function doGet() {
  return resposta({ ok: true, info: 'Use POST.' });
}

// Impede que um texto começando com = + - @ vire fórmula na planilha.
function semFormula(t) {
  return /^[=+\-@]/.test(t) ? "'" + t : t;
}

function resposta(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
