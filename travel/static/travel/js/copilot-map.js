(() => {
  function initializeCopilotMap() {
    const element = document.getElementById("copilotMap");
    if (!element) return;

    const tileNotice = document.getElementById("copilotMapTileNotice");
    const routeDataElement = document.getElementById("copilot-route-points-data");
    const configElement = document.getElementById("map-config-data");

    function showTileNotice(message) {
      if (!tileNotice) return;
      tileNotice.textContent = message;
      tileNotice.hidden = false;
    }

    function showMapMessage(message) {
      element.replaceChildren();
      const wrapper = document.createElement("div");
      wrapper.className = "h-100 d-flex flex-column align-items-center justify-content-center text-center p-4 text-muted";
      const text = document.createElement("p");
      text.className = "mb-0";
      text.textContent = message;
      wrapper.appendChild(text);
      element.appendChild(wrapper);
    }

    let routePoints = [];
    let mapConfig = {};
    try {
      routePoints = JSON.parse(routeDataElement?.textContent || "[]");
      if (!Array.isArray(routePoints)) routePoints = [];
    } catch (_) {
      routePoints = [];
    }
    try {
      mapConfig = JSON.parse(configElement?.textContent || "{}");
    } catch (_) {
      mapConfig = {};
    }

    routePoints = routePoints
      .map((point) => {
        const lat = point.lat === null || point.lat === "" ? NaN : Number(point.lat);
        const lon = point.lon === null || point.lon === "" ? NaN : Number(point.lon);
        return { ...point, lat, lon };
      })
      .filter((point) => (
        Number.isFinite(point.lat) && point.lat >= -90 && point.lat <= 90 &&
        Number.isFinite(point.lon) && point.lon >= -180 && point.lon <= 180
      ));

    if (!routePoints.length) {
      showMapMessage("No scheduled stops have valid map coordinates. Attraction latitude and longitude are needed to display route markers.");
      return;
    }

    if (!window.L) {
      showMapMessage("The map library could not load. Check your connection and refresh to view the route map.");
      return;
    }

    if (!element.clientWidth || !element.clientHeight) {
      showMapMessage("The map area is not visible yet. Resize the page or refresh to load the route map.");
      return;
    }

    const scheduledCount = Number(element.dataset.stopCount || routePoints.length);
    if (Number.isFinite(scheduledCount) && routePoints.length < scheduledCount) {
      const coordinateNotice = document.getElementById("copilotMapCoordinateNotice");
      if (coordinateNotice) coordinateNotice.hidden = false;
    }

    const map = L.map(element, { scrollWheelZoom: false });
    const tileUrl = String(mapConfig.tile_url || "").trim();
    const tileAttribution = String(mapConfig.tile_attribution || "").trim();
    if (tileUrl && tileAttribution) {
      const tileLayer = L.tileLayer(tileUrl, { maxZoom: 19, attribution: tileAttribution });
      let tileFailureShown = false;
      tileLayer.on("tileerror", () => {
        if (tileFailureShown) return;
        tileFailureShown = true;
        tileLayer.remove();
        showTileNotice("The configured map tile provider failed. Stops and routes remain available.");
      });
      tileLayer.addTo(map);
    } else {
      showTileNotice("Map tiles are not configured. Stops and routes remain visible without a basemap.");
    }

    const colors = ["#2563eb", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4"];
    const daySegments = new Map();
    const bounds = [];

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (character) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[character]);
    }

    routePoints.forEach((point) => {
      const day = Number.isInteger(Number(point.day)) && Number(point.day) > 0
        ? Number(point.day)
        : 1;
      const dayColor = colors[(day - 1) % colors.length];
      const latlng = [point.lat, point.lon];
      const marker = L.circleMarker(latlng, {
        radius: 9,
        fillColor: dayColor,
        color: "#ffffff",
        weight: 2,
        opacity: 1,
        fillOpacity: 0.9
      }).addTo(map);

      const cost = Number(point.cost || 0);
      marker.bindPopup(`
        <div style="min-width:170px;">
          <span style="background:${dayColor}; color:#fff; padding:2px 8px; border-radius:12px; font-size:11px;">Day ${day}</span>
          <strong style="display:block; margin-top:5px; font-size:14px;">${escapeHtml(point.name)}</strong>
          <small style="color:#64748b; display:block;">${escapeHtml(point.category || "Attraction")} &middot; ${escapeHtml(point.time || "Scheduled")}</small>
          <small style="color:#16a34a; font-weight:600;">Cost: ${cost === 0 ? "Free" : `₹${cost}`}</small>
        </div>
      `);

      bounds.push(latlng);
      if (!daySegments.has(day)) daySegments.set(day, []);
      daySegments.get(day).push(latlng);
    });

    daySegments.forEach((coordinates, day) => {
      if (coordinates.length < 2) return;
      L.polyline(coordinates, {
        color: colors[(day - 1) % colors.length],
        weight: 4,
        opacity: 0.8,
        dashArray: "6, 8"
      }).addTo(map);
    });

    if (bounds.length === 1) {
      map.setView(bounds[0], 13);
    } else {
      map.fitBounds(L.latLngBounds(bounds).pad(0.18), { maxZoom: 14 });
    }

    window.requestAnimationFrame(() => map.invalidateSize());
    window.addEventListener("pagehide", (event) => {
      if (!event.persisted) map.remove();
    }, { once: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeCopilotMap, { once: true });
  } else {
    initializeCopilotMap();
  }
})();
