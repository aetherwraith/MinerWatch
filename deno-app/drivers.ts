// Zero-dependency Miner Drivers for Deno (Bitaxe/Nmaxe HTTP & CGMiner TCP)

export interface MinerStatus {
  ip: string;
  family: "nmaxe" | "bitaxe" | "cgminer" | "unknown";
  hostname?: string;
  hashrate_ths: number;
  power_w: number;
  efficiency_j_th: number;
  temp_chip_c?: number;
  temp_vr_c?: number;
  fan_pct?: number;
  error_pct?: number;
  freq_mhz?: number;
  voltage_mv?: number;
  online: boolean;
}

/** Fetch telemetry from Nmaxe / Bitaxe HTTP REST API */
export async function probeHttpMiner(ip: string): Promise<MinerStatus | null> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);

    const res = await fetch(`http://${ip}/api/system/info`, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!res.ok) return null;
    const data = await res.json();

    const hrGhs = data.hashRate || data.hashrate || 0;
    const hrThs = hrGhs / 1000.0;
    const power = data.power || data.power_w || 0;
    const eff = hrThs > 0 ? power / hrThs : 0;
    const chipTemp = data.temp || data.temp_chip || data.chip_temp;
    const vrTemp = data.vrTemp || data.temp_vr;
    const fan = data.fanSpeed || data.fan_pct || data.fan;

    const autofanspeed = data.autofanspeed !== undefined ? Number(data.autofanspeed) : undefined;
    const tempTarget = data.tempTarget ?? data.pidTargetTemp ?? data.targetTemp;

    const isNmaxe = Boolean(data.nmaxeVersion || data.smallCoreCount);
    return {
      ip,
      family: isNmaxe ? "nmaxe" : "bitaxe",
      hostname: data.hostname || data.miner_name || `miner-${ip.split(".").pop()}`,
      hashrate_ths: Math.round(hrThs * 1000) / 1000,
      power_w: Math.round(power * 10) / 10,
      efficiency_j_th: Math.round(eff * 100) / 100,
      temp_chip_c: chipTemp ? Math.round(chipTemp * 10) / 10 : undefined,
      temp_vr_c: vrTemp ? Math.round(vrTemp * 10) / 10 : undefined,
      fan_pct: fan ? Math.round(fan) : undefined,
      freq_mhz: data.frequency || data.freq,
      voltage_mv: data.coreVoltage || data.voltage,
      autofanspeed,
      temp_target: tempTarget != null ? Number(tempTarget) : undefined,
      raw: data,
      online: true,
    } as any;
  } catch (_err) {
    return null;
  }
}

/** Send raw TCP JSON command to CGMiner API (Port 4028) */
export async function probeCgminerTcp(ip: string, command: string = "summary"): Promise<Record<string, unknown> | null> {
  try {
    const conn = await Deno.connect({ hostname: ip, port: 4028 });
    const encoder = new TextEncoder();
    const decoder = new TextDecoder();

    const cmdPayload = JSON.stringify({ command });
    await conn.write(encoder.encode(cmdPayload));

    const buffer = new Uint8Array(8192);
    const readBytes = await conn.read(buffer);
    conn.close();

    if (!readBytes) return null;
    const rawStr = decoder.decode(buffer.subarray(0, readBytes)).trim().replace(/\0/g, "");
    return JSON.parse(rawStr);
  } catch (_err) {
    return null;
  }
}
