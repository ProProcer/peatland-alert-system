const assert = require('node:assert/strict');
const fs = require('node:fs');
const {measurement, explanation} = require('./explain.js');
const snapshot = JSON.parse(fs.readFileSync(__dirname + '/assets/coverage-snapshot.json', 'utf8'));
const features = snapshot.feeds['features.json'];
const risks = snapshot.feeds['risk.json'];
for (const feature of features) {
  for (const horizon of [24,48,72]) {
    const risk = risks.find(row => row.cell_id === feature.cell_id && row.horizon_h === horizon);
    const output = explanation(feature, risk, horizon);
    assert.equal(output.horizon,horizon);
    assert.equal(output.risk,risk);
    for (const factor of output.factors) {
      assert(factor.width >= 0 && factor.width <= 100);
      assert.equal(factor.contribution,risk.top_factors.find(row=>row.feature===factor.feature).contribution);
      const group = ['peat','weather','derived','fire'].find(key=>factor.feature in feature[key]);
      assert.equal(factor.raw,feature[group][factor.feature]);
    }
  }
}
assert.match(measurement({weather:{sm_27_81:null}},'sm_27_81').text,/Unavailable/);
assert.equal(measurement({derived:{rain_24h_mm:0}},'rain_24h_mm').raw,0);
assert.equal(explanation(null,null,24).factors.length,0);
const signed=explanation(null,{top_factors:[{feature:'temp_c',contribution:-2},{feature:'sm_27_81',contribution:1}]},48);
assert.equal(signed.factors[0].direction,'Negative model factor');
assert.equal(signed.factors[1].width,50);
console.log(`PASS: explanations match supplied factors and measurements for ${features.length} cells across three horizons; nulls, zeroes and signed factors preserved.`);
