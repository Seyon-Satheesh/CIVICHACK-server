/* CivicSpeak admin console: map pin placement and file-name preview. */
(function () {
  // Show chosen file names in the drop zone.
  document.querySelectorAll(".drop input[type=file]").forEach(function (input) {
    input.addEventListener("change", function () {
      var out = input.closest(".drop").querySelector("[data-filenames]");
      var names = Array.prototype.map.call(input.files, function (f) { return f.name; });
      if (out) out.textContent = names.length ? "Attached: " + names.join(", ") : "PDF, DOCX or images";
    });
  });

  // Click the map to place the pin; the circle shows the radius of impact.
  var el = document.getElementById("place-map");
  if (!el || typeof L === "undefined") return;
  var lat = document.getElementById("id_latitude"), lng = document.getElementById("id_longitude");
  var radius = document.getElementById("id_impact_radius_km");
  var start = el.dataset.lat && el.dataset.lng
    ? [parseFloat(el.dataset.lat), parseFloat(el.dataset.lng)]
    : [parseFloat(el.dataset.defaultLat), parseFloat(el.dataset.defaultLng)];

  var map = L.map(el).setView(start, el.dataset.lat ? 15 : 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"
  }).addTo(map);

  var marker = null, circle = null;
  function km() { var v = parseFloat(radius && radius.value); return isNaN(v) ? 1 : v; }
  function draw(latlng) {
    if (marker) { marker.setLatLng(latlng); circle.setLatLng(latlng).setRadius(km() * 1000); }
    else {
      marker = L.marker(latlng).addTo(map);
      circle = L.circle(latlng, { radius: km() * 1000, color: "#1d3b52", weight: 2, fillOpacity: 0.12 }).addTo(map);
    }
    lat.value = latlng.lat.toFixed(6); lng.value = latlng.lng.toFixed(6);
  }
  if (el.dataset.lat && el.dataset.lng) draw(L.latLng(start[0], start[1]));
  map.on("click", function (e) { draw(e.latlng); });
  if (radius) radius.addEventListener("input", function () { if (circle) circle.setRadius(km() * 1000); });
})();
