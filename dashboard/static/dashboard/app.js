(function () {
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
})();
