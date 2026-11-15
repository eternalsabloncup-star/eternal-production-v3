import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { SettingsPanel, PasswordChangeForm } from "./SettingsPanel";
import { createSettingsApi, SettingsApi } from "./api";

afterEach(() => { vi.unstubAllGlobals(); });
function adapter() {
  const request = vi.fn(async (path: string): Promise<unknown> => {
    if (path === "/users") return { revision: 0, items: [{ id: 1, username: "user", display_name: "User", is_active: true }] };
    if (path === "/groups") return { revision: 0, items: [{ id: 1, name: "Protected", system: true, active: true }, { id: 2, name: "Empty", system: false, active: true }] };
    if (path === "/capabilities") return { revision: 0, items: [{ code: "task.export", module: "task", action: "export", scope: "branch" }] };
    if (path.endsWith("/grants")) return { revision: 0, items: [] };
    return { revision: 1 };
  });
  return { request, api: { request } as SettingsApi };
}
function typeContinuously(label: string, value: string) {
  const input = screen.getByLabelText(label) as HTMLInputElement;
  input.focus();
  for (const character of value) {
    fireEvent.change(input, { target: { value: input.value + character } });
    expect(screen.getByLabelText(label)).toBe(input);
    expect(document.activeElement).toBe(input);
  }
  expect(input.value).toContain(value);
}
async function ready() { await waitFor(() => expect(screen.getByText("Edit user")).toBeEnabled()); }

describe("isolated Settings UI", () => {
  it("retains focus while typing account, reason, search, group and scope forms", async () => {
    const { api } = adapter(); render(<SettingsPanel api={api} />); await ready();
    for (const [label, value] of [["Username", "operator"], ["Nama tampilan", "Operator Baru"], ["Password awal", "test-password-123"], ["Alasan perubahan", "Owner request"], ["Cari username", "oper"]]) typeContinuously(label, value);
    fireEvent.click(screen.getByText("Edit user"));
    typeContinuously("Password sementara baru", "temporary-password");
    fireEvent.click(screen.getByRole("button", { name: "Grup & Permission" }));
    typeContinuously("Nama grup baru", "Packing");
    fireEvent.change(screen.getByLabelText("Grup akses"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByLabelText("Cabang (pisahkan koma)")).toBeEnabled());
    typeContinuously("Cabang (pisahkan koma)", "A,B");
    fireEvent.change(screen.getByLabelText("Ownership"), { target: { value: "selected" } });
    typeContinuously("ID assignment (pisahkan koma)", "10,20");
  });

  it("does not report success for failed account creation and clears password", async () => {
    const { api, request } = adapter();
    request.mockImplementation(async (path, ...args) => {
      if (args.length && path === "/users") throw new Error("Revision conflict");
      if (path === "/users") return { revision: 0, items: [{ id: 1, username: "user", display_name: "User", is_active: true }] };
      return { revision: 0, items: [] };
    });
    render(<SettingsPanel api={api} confirmAction={() => true} />); await ready();
    typeContinuously("Alasan perubahan", "Owner"); typeContinuously("Username", "new"); typeContinuously("Nama tampilan", "New"); typeContinuously("Password awal", "test-password-123");
    fireEvent.click(screen.getByText("Simpan pengguna"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Revision conflict");
    expect(screen.getByRole("status")).not.toHaveTextContent("tersimpan");
    expect(screen.getByLabelText("Password awal")).toHaveValue("");
  });

  it("requires confirmation before sending account changes", async () => {
    const { api, request } = adapter(); render(<SettingsPanel api={api} confirmAction={() => false} />); await ready();
    typeContinuously("Alasan perubahan", "Owner");
    fireEvent.click(screen.getByText("Nonaktifkan user"));
    await waitFor(() => expect(screen.getByText("Nonaktifkan user")).toBeEnabled());
    expect(request.mock.calls.some(([path]) => path.endsWith("/active"))).toBe(false);
  });

  it("protects system groups and ordinary groups start unchecked", async () => {
    const { api } = adapter(); render(<SettingsPanel api={api} />); await ready();
    fireEvent.click(screen.getByRole("button", { name: "Grup & Permission" }));
    fireEvent.change(screen.getByLabelText("Grup akses"), { target: { value: "1" } });
    expect(screen.getByText(/System privilege terlindungi/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Grup akses")).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Grup akses"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByRole("checkbox")).toBeEnabled());
    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("password form retains focus, clears secrets and waits for API success", async () => {
    const request = vi.fn().mockRejectedValue(new Error("Wrong password")); const done = vi.fn();
    render(<PasswordChangeForm api={{ request }} onChanged={done} />);
    typeContinuously("Password saat ini", "current-password"); typeContinuously("Password baru", "new-password-123");
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong password");
    expect(done).not.toHaveBeenCalled(); expect(screen.getByLabelText("Password baru")).toHaveValue("");
  });

  it("adapter rejects HTTP failures and never stores tokens", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Forbidden" }), { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createSettingsApi("/api/v1", () => "isolated-token").request("/users")).rejects.toThrow("Forbidden");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/settings/users");
    expect(fetchMock.mock.calls[0][1].cache).toBe("no-store");
  });
});

it("runtime mode shows enforced status, endpoint map, and role grant packs", async () => {
  const { api, request } = adapter();
  request.mockImplementation(async (path: string) => {
    if (path === "/authorization-status") {
      return {
        workflow_authorization: "enforced",
        active_now: true,
        automatic_grant_import: false,
        production_endpoints_mapped: 70,
        inventory_audit: { conclusion: "not_run" },
        branch_management: "Cabang via grant.",
        mapping_review_required: {
          "production.tracking.read": {
            status: "mapped_manual_packs",
            impact: "read ≠ link",
            recommendation: "grant terpisah",
            owner_decision: "manual",
          },
        },
        role_grant_packs: {
          automatic_apply_allowed: false,
          usage: "Grant manual via Pengaturan.",
          packs: { driver: { label: "Driver", ownership_default: "all", capabilities: ["loading.record"], notes: "POD" } },
        },
      };
    }
    if (path === "/users" || path.startsWith("/users?")) {
      return { revision: 0, items: [{ id: 1, username: "user", display_name: "User", is_active: true }] };
    }
    if (path === "/groups") return { revision: 0, items: [] };
    if (path === "/capabilities") return { revision: 0, items: [] };
    return { revision: 0, items: [] };
  });
  render(<SettingsPanel api={api} runtime workflowAuthorization="legacy" />);
  expect(await screen.findByTestId("authorization-status")).toHaveAttribute("data-mode", "enforced");
  expect(screen.getByTestId("endpoint-map-count")).toHaveTextContent("70");
  expect(screen.getByTestId("role-grant-packs")).toHaveTextContent("Driver");
  expect(screen.getByTestId("mapping-review")).toHaveTextContent("production.tracking.read");
  expect(screen.getByText(/Mode enforced AKTIF/)).toBeInTheDocument();
});

it("reports partial grant writes and does not retry the saved grant", async () => {
  const { api, request } = adapter();
  let writes = 0;
  request.mockImplementation(async (path, ...args) => {
    if (path === "/users") return { revision: writes, items: [{ id: 1, username: "user", display_name: "User", is_active: true }] };
    if (path === "/groups") return { revision: writes, items: [{ id: 2, name: "Empty", system: false, active: true }] };
    if (path === "/capabilities") return { revision: writes, items: ["task.export", "job.export"].map(code => ({ code, module: "export", scope: "branch", action: "export" })) };
    if (path.endsWith("/grants") && args.length) {
      writes++;
      if (writes === 2) throw new Error("Revision conflict");
      return { revision: 1 };
    }
    return { revision: writes, items: [] };
  });
  render(<SettingsPanel api={api} confirmAction={() => true} />); await ready();
  typeContinuously("Alasan perubahan", "Owner");
  fireEvent.click(screen.getByRole("button", { name: "Grup & Permission" }));
  fireEvent.change(screen.getByLabelText("Grup akses"), { target: { value: "2" } });
  await waitFor(() => expect(screen.getByLabelText("Cabang (pisahkan koma)")).toBeEnabled());
  typeContinuously("Cabang (pisahkan koma)", "A");
  for (const checkbox of screen.getAllByRole("checkbox")) fireEvent.click(checkbox);
  fireEvent.click(screen.getByText("Berikan permission terpilih"));
  expect(await screen.findByRole("alert")).toHaveTextContent("1 grant tersimpan; 1 belum disimpan");
  expect(screen.getAllByRole("checkbox")[0]).not.toBeChecked();
  expect(screen.getAllByRole("checkbox")[1]).toBeChecked();
});
