const solc = require('solc%s');
const input = %s;
if (typeof expectedCompiler !== 'undefined') {
  const actual = solc.version().match(/^(\d+\.\d+\.\d+)\+commit\.([0-9a-fA-F]{8})/);
  if (!actual || actual[1] !== expectedCompiler.version ||
      (expectedCompiler.commit && actual[2].toLowerCase() !== expectedCompiler.commit)) {
    console.log(JSON.stringify({ errors: [{ severity: 'error', reason_code: 'compiler_unavailable',
      message: 'Installed JavaScript compiler does not match the requested Solidity version and commit.' }] }));
    process.exit(0);
  }
}
const compile = solc.compileStandardWrapper || solc.compileStandard || solc.compile;
var output = compile.call(solc, JSON.stringify(input));
if (output instanceof Object) {
  output = JSON.stringify(output);
}
console.log(output)
