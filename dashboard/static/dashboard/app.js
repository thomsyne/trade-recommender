(function () {
  const activeNavigationLink = document.querySelector(".sidebar nav .active");
  if (activeNavigationLink && window.matchMedia("(max-width: 950px)").matches) {
    activeNavigationLink.scrollIntoView({ block: "nearest", inline: "center" });
  }

  window.renderMarketChart = function (id, candles) {
    const canvas = document.getElementById(id);
    if (!canvas || !candles.length) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = 390;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const context = canvas.getContext("2d");
    context.scale(ratio, ratio);
    context.fillStyle = "#111a17";
    context.fillRect(0, 0, width, height);
    const values = candles.flatMap((candle) => [candle.high, candle.low]);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const range = high - low || 1;
    const padding = 28;
    const y = (value) =>
      padding + ((high - value) / range) * (height - padding * 2);
    const step = (width - padding * 2) / candles.length;
    context.strokeStyle = "rgba(217,231,221,.08)";
    context.lineWidth = 1;
    for (let line = 1; line < 5; line += 1) {
      const lineY = padding + ((height - padding * 2) / 5) * line;
      context.beginPath();
      context.moveTo(padding, lineY);
      context.lineTo(width - padding, lineY);
      context.stroke();
    }
    candles.forEach((candle, index) => {
      const x = padding + index * step + step / 2;
      const rising = candle.close >= candle.open;
      context.strokeStyle = rising ? "#7fc49a" : "#d8836f";
      context.fillStyle = context.strokeStyle;
      context.beginPath();
      context.moveTo(x, y(candle.high));
      context.lineTo(x, y(candle.low));
      context.stroke();
      const top = y(Math.max(candle.open, candle.close));
      const bottom = y(Math.min(candle.open, candle.close));
      context.fillRect(
        x - Math.max(1.5, step * 0.28),
        top,
        Math.max(3, step * 0.56),
        Math.max(1, bottom - top),
      );
    });
  };

  document.querySelectorAll(".cohort-selector").forEach((form) => {
    const script = form.querySelector('script[type="application/json"]');
    if (!script) return;
    const policy = JSON.parse(script.textContent);
    const boxes = Array.from(form.querySelectorAll('input[type="checkbox"]'));
    const update = () => {
      let total = Number(policy.base_total_risk_cad || 0);
      const directions = Object.fromEntries(
        Object.entries(policy.base_currency_direction_risk_cad || {}).map(([key, value]) => [key, Number(value)]),
      );
      boxes.forEach((box) => {
        box.closest(".selector-card").classList.toggle("selected", box.checked);
        if (!box.checked) return;
        const risk = Number(box.dataset.risk);
        total += risk;
        box.dataset.legs.split(",").filter(Boolean).forEach((leg) => {
          directions[leg] = (directions[leg] || 0) + risk;
        });
      });
      const largest = Math.max(0, ...Object.values(directions));
      const valid = total <= Number(policy.aggregate_risk_cap_cad) && largest <= Number(policy.currency_direction_risk_cap_cad);
      form.querySelector("[data-total-risk]").textContent = `C$${total.toFixed(0)} / C$${Number(policy.aggregate_risk_cap_cad).toFixed(0)}`;
      form.querySelector("[data-largest-direction]").textContent = `C$${largest.toFixed(0)} / C$${Number(policy.currency_direction_risk_cap_cad).toFixed(0)}`;
      const result = form.querySelector("[data-policy-result]");
      result.textContent = valid ? "FITS" : "EXCEEDS CAP";
      result.classList.toggle("invalid", !valid);
      const submit = form.querySelector('button[type="submit"]');
      if (submit) submit.disabled = !valid;
    };
    boxes.forEach((box) => box.addEventListener("change", update));
    update();
  });
})();
