(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("thermal-data").textContent);
  const group = document.getElementById("group");
  const record = document.getElementById("record");
  const average = values => values.reduce((a, b) => a + b, 0) / values.length;
  const range = values => Math.max(...values) - Math.min(...values);
  function score(sensors, name) {
    const iv = sensors.slice(0, 6), mt = sensors.slice(6);
    const ivMean = average(iv), centered = iv.map(value => value - ivMean);
    const features = [ivMean, ...centered, range(iv), Math.abs(iv[4] - iv[5]), Math.max(...centered.slice(0, 4))];
    if (name === "paired_motor") {
      const delta = iv.map((value, i) => value - mt[i]), mid = average(delta);
      features.push(mid, ...delta.map(value => value - mid), range(delta), Math.max(...delta.slice(0, 4)), Math.abs(delta[4] - delta[5]));
    }
    const model = data.models[name], p = model.model;
    const z = features.reduce((acc, x, i) => acc + p.coef[i + 1] * ((x - p.mean[i]) / p.sd[i]), p.coef[0]);
    const probability = 1 / (1 + Math.exp(-Math.max(-35, Math.min(35, z))));
    return {probability, fault: probability >= model.cut};
  }
  function render() {
    const rows = data.cases[group.value], index = Number(record.value) - 1;
    const item = rows[index];
    document.getElementById("position").textContent = String(index + 1) + " / " + rows.length;
    document.getElementById("count").textContent = item.count;
    document.getElementById("actual").textContent = item.label === 1 ? "故障" : "正常";
    const cells = document.querySelectorAll("#sensors tbody tr");
    cells.forEach((tr, i) => {
      tr.cells[1].textContent = item.sensors[i];
      tr.cells[2].textContent = item.sensors[6 + i];
    });
    for (const name of ["inverter", "paired_motor"]) {
      const value = score(item.sensors, name), tr = document.getElementById(name);
      tr.cells[1].textContent = value.probability.toFixed(5);
      tr.cells[2].textContent = data.models[name].cut.toFixed(2);
      tr.cells[3].textContent = value.fault ? "故障" : "正常";
    }
  }
  function changeGroup() {
    record.max = data.cases[group.value].length;
    record.value = 1;
    render();
  }
  group.addEventListener("change", changeGroup);
  record.addEventListener("input", render);
  changeGroup();
})();
