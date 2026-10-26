document.addEventListener("DOMContentLoaded", async () => {
  const element = document.getElementById("tripRouteMap");
  const dataElement = document.getElementById("route-points-data");
  const configElement = document.getElementById("map-config-data");
  const summary = document.getElementById("routeSummary");
  const tileNotice = document.getElementById("mapTileNotice");
  if (!element || !dataElement) return;

  if (!window.L) {
    element.innerHTML = '<div class="map-empty"><i class="fa-regular fa-map fa-2x mb-2 text-muted"></i><p class="mb-0">The interactive map library could not load.<br><small class="text-muted">Check your internet connection and refresh.</small></p></div>';
    if (summary) summary.textContent = "Map library unavailable.";
    if (tileNotice) {
      tileNotice.textContent = "Interactive map previews are unavailable; itinerary details and distances remain available.";
      tileNotice.hidden = false;
    }
    return;
  }

  let points = [];
  let mapConfig = {};
  try {
    points = JSON.parse(dataElement.textContent || "[]");
  } catch (_) {
    points = [];
  }
  try {
    mapConfig = JSON.parse(configElement?.textContent || "{}");
  } catch (_) {
    mapConfig = {};
  }

  // Filter valid geographic coordinates
  points = points.filter(p => (
    typeof p.lat === "number" && !isNaN(p.lat) && p.lat >= -90 && p.lat <= 90 &&
    typeof p.lon === "number" && !isNaN(p.lon) && p.lon >= -180 && p.lon <= 180
  ));

  if (!points.length) {
    element.innerHTML = '<div class="map-empty"><i class="fa-solid fa-location-dot fa-2x mb-2 text-muted"></i><p class="mb-0 fw-semibold">No geographic coordinates available</p><small class="text-muted">Attractions in this itinerary do not have coordinates yet. Itinerary details are listed below.</small></div>';
    if (summary) summary.innerHTML = '<small class="text-muted">Add attraction coordinates to view map routes.</small>';
    return;
  }

  const map = L.map(element, { scrollWheelZoom: false });
  const tileLayers = new Map();
  let tileProviderUnavailable = false;
  const previewMaps = new Map();
  const markersByItemId = new Map();

  function showTileNotice(message) {
    if (!tileNotice) return;
    tileNotice.textContent = message;
    tileNotice.hidden = false;
  }

  function addConfiguredTiles(targetMap) {
    const url = (mapConfig.tile_url || "").trim();
    const attribution = (mapConfig.tile_attribution || "").trim();
    if (!url || !attribution) {
      showTileNotice("Map tiles are not configured. Set SMARTTRIP_MAP_TILE_URL and SMARTTRIP_MAP_TILE_ATTRIBUTION locally; stops and distances remain available.");
      return;
    }
    if (tileProviderUnavailable) return;

    const layer = L.tileLayer(url, { maxZoom: 19, attribution });
    layer.on("tileerror", () => {
      if (tileProviderUnavailable) return;
      tileProviderUnavailable = true;
      tileLayers.forEach(existingLayer => existingLayer.remove());
      tileLayers.clear();
      showTileNotice("The configured map tile provider failed. Tile requests are paused; stops and routes remain available.");
    });
    tileLayers.set(targetMap, layer);
    layer.addTo(targetMap);
  }

  addConfiguredTiles(map);

  const dayColors = ["#6558d3", "#0f9f91", "#e05638", "#2563eb", "#d97706", "#7c3aed"];
  const latlngs = [];
  const routeBase = (mapConfig.routing_url || "").trim().replace(/\/+$/, "");

  points.forEach((point, index) => {
    const latlng = [Number(point.lat), Number(point.lon)];
    latlngs.push(latlng);

    const dayColor = dayColors[(Number(point.day) - 1) % dayColors.length] || "#6558d3";
    const icon = L.divIcon({
      className: "smarttrip-map-marker-wrap",
      html: `<span class="smarttrip-map-marker" style="background:${dayColor}"><b>${index + 1}</b></span>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16]
    });

    let popupHtml = `<div style="min-width:180px; font-family: inherit;">
      <strong style="font-size:14px; display:block; margin-bottom:4px;">${escapeHtml(point.name)}</strong>
      <div style="font-size:12px; color:#555; margin-bottom:4px;">
        <span class="badge" style="background:#eef2ff; color:#3730a3; padding:2px 6px; border-radius:4px;">Day ${point.day}</span>
        ${point.time ? `<span style="margin-left:4px;">· <i class="fa-regular fa-clock"></i> ${escapeHtml(point.time)}</span>` : ""}
      </div>
      <div style="font-size:12px; color:#475569;">
        <strong>Category:</strong> ${escapeHtml(point.category || "Attraction")}
      </div>`;

    if (point.cost !== undefined && point.cost > 0) {
      popupHtml += `<div style="font-size:12px; color:#475569;"><strong>Cost:</strong> ₹${point.cost}</div>`;
    }
    if (point.duration) {
      popupHtml += `<div style="font-size:12px; color:#475569;"><strong>Duration:</strong> ~${point.duration}h</div>`;
    }
    if (point.reason) {
      popupHtml += `<div style="font-size:11px; color:#6b7280; margin-top:4px; font-style:italic; border-top:1px solid #eee; padding-top:4px;">${escapeHtml(point.reason)}</div>`;
    }
    popupHtml += `</div>`;

    const marker = L.marker(latlng, { icon }).addTo(map).bindPopup(popupHtml);
    if (point.item_id !== undefined) markersByItemId.set(String(point.item_id), marker);
  });

  if (latlngs.length === 1) {
    map.setView(latlngs[0], 14);
  } else {
    map.fitBounds(L.latLngBounds(latlngs).pad(0.18), { maxZoom: 14 });
  }

  async function addRoadRoutes() {
  const days = [...new Set(points.map(point => Number(point.day)))].sort((a, b) => a - b);
  let totalDistance = 0;
  let totalDuration = 0;
  let roadRoutes = 0;
  let fallbackRoutes = 0;

  for (const day of days) {
    const dayPoints = points.filter(point => Number(point.day) === day);
    const coords = dayPoints.map(point => [Number(point.lat), Number(point.lon)]);
    if (coords.length < 2) continue;

    const dayColor = dayColors[(day - 1) % dayColors.length] || "#6558d3";

    try {
      if (!routeBase) throw new Error("Routing service is not configured");
      const coordinates = dayPoints.map(point => `${point.lon},${point.lat}`).join(";");
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 6000);

      let response;
      try {
        response = await fetch(
          `${routeBase}/route/v1/driving/${coordinates}?overview=full&geometries=geojson&steps=false`,
          { headers: { "Accept": "application/json" }, signal: controller.signal }
        );
      } finally {
        clearTimeout(timeoutId);
      }

      if (!response.ok) throw new Error("Routing service returned non-200");
      const data = await response.json();
      if (!data.routes || !data.routes.length) throw new Error("No route returned");

      const route = data.routes[0];
      const routeDistance = Number(route.distance);
      const routeDuration = Number(route.duration);
      if (!route.geometry || !Number.isFinite(routeDistance) || routeDistance < 0 ||
          !Number.isFinite(routeDuration) || routeDuration < 0) {
        throw new Error("Routing service returned incomplete route estimates");
      }
      L.geoJSON(route.geometry, {
        style: { color: dayColor, weight: 5, opacity: 0.85 }
      }).addTo(map);

      totalDistance += routeDistance;
      totalDuration += routeDuration;
      roadRoutes++;

      if (Array.isArray(route.legs)) {
        route.legs.forEach((leg, index) => {
          const previousPoint = dayPoints[index];
          const point = dayPoints[index + 1];
          if (!previousPoint || !point) return;

          const card = document.querySelector(`[data-itinerary-item="${point.item_id}"]`);
          if (!card || card.dataset.previousItemId !== String(previousPoint.item_id)) return;

          const distance = Number(leg.distance);
          const duration = Number(leg.duration);
          const details = [];
          if (Number.isFinite(distance) && distance >= 0) {
            details.push(`Estimated road distance: ${(distance / 1000).toFixed(1)} km`);
          }
          if (Number.isFinite(duration) && duration >= 0) {
            details.push(`estimated driving time: ${Math.round(duration / 60)} min`);
          }
          const output = document.querySelector(`[data-road-distance-for="${point.item_id}"]`);
          if (output && details.length) {
            output.textContent = `${details.join("; ")}.`;
            output.hidden = false;
          }
        });
      }
    } catch (_) {
      // Straight-line fallback when OSRM routing is unavailable or times out
      L.polyline(coords, {
        color: dayColor,
        weight: 4,
        dashArray: "7 8",
        opacity: 0.8
      }).addTo(map);
      fallbackRoutes++;
    }
  }

  if (summary) {
    if (roadRoutes > 0) {
      summary.innerHTML = `<span><i class="fa-solid fa-route me-1 text-primary"></i><strong>${(totalDistance / 1000).toFixed(1)} km</strong> estimated road distance</span>
        <span class="ms-3"><i class="fa-regular fa-clock me-1 text-primary"></i><strong>${Math.round(totalDuration / 60)} min</strong> driving</span>
        <div class="small text-muted mt-1">OSRM road routing across ${roadRoutes} day(s).${fallbackRoutes > 0 ? ` (${fallbackRoutes} day(s) use straight-line fallback).` : ""}</div>`;
    } else if (points.length > 1) {
      summary.innerHTML = `<span><i class="fa-solid fa-route me-1 text-primary"></i>Road routing unavailable</span>
        <div class="small text-muted mt-1">Straight-line distances are shown per stop where coordinates are available; dashed lines show the stop sequence.</div>`;
    } else {
      summary.innerHTML = `<span class="small text-muted"><i class="fa-solid fa-location-dot me-1 text-primary"></i>Single mapped attraction stop shown.</span>`;
    }
  }
  }

  addRoadRoutes();

  function initializePreview(preview) {
    if (previewMaps.has(preview)) return;
    const lat = Number(preview.dataset.lat);
    const lon = Number(preview.dataset.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) return;

    const previewMap = L.map(preview, {
      scrollWheelZoom: false,
      zoomControl: false,
      doubleClickZoom: false,
      attributionControl: true
    }).setView([lat, lon], 14);
    previewMaps.set(preview, previewMap);
    addConfiguredTiles(previewMap);
    L.circleMarker([lat, lon], {
      radius: 7,
      color: "#ffffff",
      weight: 2,
      fillColor: "#6558d3",
      fillOpacity: 1
    }).addTo(previewMap);
    setTimeout(() => previewMap.invalidateSize(), 0);
  }

  function destroyPreview(preview) {
    const previewMap = previewMaps.get(preview);
    if (!previewMap) return;
    const previewTileLayer = tileLayers.get(previewMap);
    if (previewTileLayer) {
      previewTileLayer.remove();
      tileLayers.delete(previewMap);
    }
    previewMap.remove();
    previewMaps.delete(preview);
  }

  const previewElements = [...document.querySelectorAll("[data-map-preview]")];
  let previewObserver = null;
  if ("IntersectionObserver" in window) {
    previewObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) initializePreview(entry.target);
        else destroyPreview(entry.target);
      });
    }, { rootMargin: "160px 0px" });
    previewElements.forEach(preview => previewObserver.observe(preview));
  } else {
    const updateVisiblePreviews = () => previewElements.forEach(preview => {
      const bounds = preview.getBoundingClientRect();
      if (bounds.bottom >= -160 && bounds.top <= window.innerHeight + 160) initializePreview(preview);
      else destroyPreview(preview);
    });
    window.addEventListener("scroll", updateVisiblePreviews, { passive: true });
    window.addEventListener("resize", updateVisiblePreviews);
    updateVisiblePreviews();
  }

  document.querySelectorAll("[data-focus-map-point]").forEach(link => {
    link.addEventListener("click", event => {
      const marker = markersByItemId.get(String(link.dataset.focusMapPoint));
      if (!marker) return;
      event.preventDefault();
      map.invalidateSize();
      map.setView(marker.getLatLng(), 15, { animate: true });
      marker.openPopup();
      element.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });

  window.addEventListener("pagehide", event => {
    if (event.persisted) return;
    previewObserver?.disconnect();
    previewMaps.forEach(previewMap => previewMap.remove());
    previewMaps.clear();
    map.remove();
    tileLayers.clear();
  });

  setTimeout(() => map.invalidateSize(), 200);

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[ch]));
  }
});
