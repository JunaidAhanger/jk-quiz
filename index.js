const MAX_DEVICES = 2;
const VALIDITY_DAYS = 365;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function normalizePhone(raw) {
  const digits = String(raw || "").replace(/\D/g, "");
  if (digits.length === 12 && digits.startsWith("91")) {
    return digits.slice(2);
  }
  return digits;
}

function normalizeCode(raw) {
  return String(raw || "").trim().toUpperCase();
}

async function handleVerifyAccess(request, env) {
  if (!env.KV) {
    return jsonResponse(
      { valid: false, message: "KV binding 'KV' is not configured." },
      500
    );
  }

  let body;
  try {
    body = await request.json();
  } catch (_) {
    return jsonResponse({ valid: false, message: "Invalid JSON request body." }, 400);
  }

  const phone = normalizePhone(body.phone);
  const code = normalizeCode(body.code);
  const deviceId = String(body.deviceId || "").trim();

  if (!/^\d{10}$/.test(phone)) {
    return jsonResponse(
      { valid: false, message: "Enter a valid 10-digit mobile number." },
      400
    );
  }
  if (!code || code.length < 4) {
    return jsonResponse({ valid: false, message: "Enter a valid access code." }, 400);
  }
  if (!deviceId || deviceId.length > 128) {
    return jsonResponse({ valid: false, message: "Missing or invalid device ID." }, 400);
  }

  const kvKey = `code:${code}`;
  const rawRecord = await env.KV.get(kvKey);
  if (!rawRecord) {
    return jsonResponse({ valid: false, message: "Access code not found." }, 404);
  }

  let record;
  try {
    record = JSON.parse(rawRecord);
  } catch (_) {
    return jsonResponse({ valid: false, message: "Corrupted license record." }, 500);
  }

  if (record.revoked) {
    return jsonResponse({ valid: false, message: "This access code has been revoked." }, 403);
  }

  if (normalizePhone(record.phone) !== phone) {
    return jsonResponse(
      { valid: false, message: "Access code is tied to a different phone number." },
      403
    );
  }

  const now = Date.now();
  let expiresAtMs = Date.parse(record.expiresAt || "");

  if (!Number.isFinite(expiresAtMs)) {
    const activatedAtMs = now;
    expiresAtMs = activatedAtMs + VALIDITY_DAYS * MS_PER_DAY;
    record.activatedAt = new Date(activatedAtMs).toISOString();
    record.expiresAt = new Date(expiresAtMs).toISOString();
  } else if (now > expiresAtMs) {
    return jsonResponse(
      { valid: false, message: "Access code expired after 365 days." },
      403
    );
  }

  const devices = Array.isArray(record.devices) ? [...record.devices] : [];
  const alreadyRegistered = devices.includes(deviceId);

  if (!alreadyRegistered) {
    if (devices.length >= MAX_DEVICES) {
      return jsonResponse(
        {
          valid: false,
          message: `Device limit reached (max ${MAX_DEVICES} devices allowed).`,
        },
        403
      );
    }
    devices.push(deviceId);
    record.devices = devices;
  }

  record.lastVerifiedAt = new Date(now).toISOString();

  const ttlSeconds = Math.max(
    60,
    Math.floor((expiresAtMs - now) / 1000) + 30 * 24 * 3600
  );

  await env.KV.put(kvKey, JSON.stringify(record), { expirationTtl: ttlSeconds });

  return jsonResponse({
    valid: true,
    expiresAt: record.expiresAt,
    devicesUsed: devices.length,
    maxDevices: MAX_DEVICES,
    message: "Access verified for 365 days.",
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/api/verify-access") {
      if (request.method === "POST") {
        return handleVerifyAccess(request, env);
      }
      return jsonResponse({ valid: false, message: "Method not allowed." }, 405);
    }

    if (env.ASSETS && typeof env.ASSETS.fetch === "function") {
      return env.ASSETS.fetch(request);
    }

    return new Response("Static assets binding not found.", { status: 500 });
  },
};