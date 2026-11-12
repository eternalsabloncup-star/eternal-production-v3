import { describe, expect, it } from "vitest";
import {
  CAPABILITY_REGISTRY,
  capabilityStatusClass,
} from "./capabilityRegistry";

describe("Slice 1I capability registry", () => {
  it("has stable ids and allowed statuses only", () => {
    const allowed = new Set(["SELESAI", "PARSIAL", "BELUM", "BLOCKED"]);
    const ids = new Set<string>();
    for (const c of CAPABILITY_REGISTRY) {
      expect(c.id).toBeTruthy();
      expect(ids.has(c.id)).toBe(false);
      ids.add(c.id);
      expect(allowed.has(c.status)).toBe(true);
      expect(c.v3Source).toBeTruthy();
      expect(c.tests !== undefined).toBe(true);
    }
  });

  it("marks multi-evidence POD as BLOCKED without inventing SELESAI", () => {
    const pod = CAPABILITY_REGISTRY.find((c) => c.id === "delivery.pod_multi_evidence");
    expect(pod?.status).toBe("BLOCKED");
  });

  it("marks packing event + physical multicolor as SELESAI with code_test", () => {
    const pack = CAPABILITY_REGISTRY.find((c) => c.id === "packing.event_contract");
    const qty = CAPABILITY_REGISTRY.find((c) => c.id === "qty.physical_multicolor");
    expect(pack?.status).toBe("SELESAI");
    expect(qty?.status).toBe("SELESAI");
    expect(capabilityStatusClass("SELESAI")).toBe("ok");
    expect(capabilityStatusClass("BLOCKED")).toBe("blocked");
  });
});
