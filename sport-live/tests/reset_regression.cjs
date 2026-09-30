const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const products = JSON.parse(fs.readFileSync(path.join(root, 'data/products.json')));
function setup() {
  const elements = new Map();
  const document = {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {
      value: '', checked: false, textContent: '', innerHTML: '', style: {},
      classList: {toggle() {}, add() {}, remove() {}},
      showModal() {}, close() {},
    });
    return elements.get(id);
  }, addEventListener() {}};
  const sandbox = {document, window: {}, AbortController,
    fetch: () => new Promise(() => {}), setInterval() {}, console};
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(root, 'static/app.js'), 'utf8'), context);
  vm.runInContext(`catalog = ${JSON.stringify(products)};`, context);
  return {context, get: document.getElementById};
}
for (const filters of ["price", "stock", "combined"]) {
for (const endSession of [false, true]) {
  const {context, get} = setup();
  get('budget').max = '6000'; get('budget').defaultValue = '6000';
  get('budget').value = filters === 'stock' ? '6000' : '50';
  get('stock-only').checked = filters !== 'price';
  get('sort').value = 'price'; get('threshold').value = '95';
  vm.runInContext("selected.add('p01'); messages=['Quero correr']; render();", context);
  assert.notEqual(get('result-count').textContent, '60 produtos');
  vm.runInContext(endSession ? "document.getElementById('new-session').onclick()" :
    "document.getElementById('reset').onclick()", context);
  assert.equal(get('result-count').textContent, '60 produtos',
    'Explorar tudo must restore the whole catalog after filters');
  assert.equal(get('sort').value, 'relevance');
  assert.equal(get('threshold').value, '55');
  assert.equal(get('cart-count').textContent, endSession ? 0 : 1);
  assert.equal(get('conversation').innerHTML, '');
}
}
console.log('Reset regression passed: explore all and end session.');

{
 const {context,get}=setup();
 for(const [query,value] of [['posso gastar até 100,00',100],['quero correr até R$ 99,90',99.9],['orçamento de 1.500,50 reais',1500.5],['até 100.00',100],['até 1.000',1000]]){
   assert.equal(vm.runInContext(`requestedBudget(${JSON.stringify(query)}).value`,context),value);
 }
 vm.runInContext("catalog="+JSON.stringify(products)+"; document.getElementById('budget').value='6000';document.getElementById('threshold').value='55'; adapt('posso gastar até 100,00');",context);
 assert.equal(get('budget').value,'100');
 assert.equal(vm.runInContext("catalog.filter(p=>p.price<=100).length",context)+' produtos',get('result-count').textContent);
 assert.equal(vm.runInContext("requestedBudget('correr 5 km')",context),null);
}
