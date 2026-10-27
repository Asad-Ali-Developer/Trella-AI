"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  BrainCircuit,
  Building2,
  CheckCircle2,
  CreditCard,
  FileText,
  Filter,
  LoaderCircle,
  Plus,
  Search,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";

import { Button } from "@/components/atoms/Button";
import { Sidebar } from "@/components/organisms/Sidebar";
import { DashboardTemplate } from "@/components/templates/DashboardTemplate";
import { workspaceStore } from "@/lib/storage";
import type { ClientSummary, User, Workspace } from "@/lib/types";
import { authService } from "@/services/AuthService";
import { clientService } from "@/services/ClientService";
import { workspaceService } from "@/services/WorkspaceService";

export default function ClientsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);

  const [clients, setClients] = useState<ClientSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");

  // New Client Modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newClientName, setNewClientName] = useState("");
  const [creating, setCreating] = useState(false);

  const loadInitialData = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const [currentUser, workspaceList] = await Promise.all([
        authService.me(),
        workspaceService.list(),
      ]);
      setUser(currentUser);
      setWorkspaces(workspaceList);

      if (workspaceList.length === 0) {
        setLoading(false);
        return;
      }

      const storedId = workspaceStore.getWorkspaceId();
      const current =
        workspaceList.find((w: Workspace) => w.id === storedId) ?? workspaceList[0];
      setSelectedWorkspace(current);
      workspaceStore.setWorkspaceId(current.id);

      await loadWorkspaceClients(current.id);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to load clients data.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadInitialData();
  }, [loadInitialData]);

  async function loadWorkspaceClients(workspaceId: string) {
    try {
      const list = await clientService.list(workspaceId);
      setClients(list);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to fetch clients.";
      setError(message);
    }
  }

  async function handleSelectWorkspace(workspace: Workspace) {
    workspaceStore.setWorkspaceId(workspace.id);
    setSelectedWorkspace(workspace);
    await loadWorkspaceClients(workspace.id);
  }

  async function handleCreateClient(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedWorkspace || !newClientName.trim()) return;
    setCreating(true);
    setError("");

    try {
      const created = await clientService.create(selectedWorkspace.id, newClientName.trim());
      setClients((prev) => [created, ...prev]);
      setNewClientName("");
      setIsModalOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Failed to create client.";
      setError(message);
    } finally {
      setCreating(false);
    }
  }

  async function handleLogout() {
    await authService.logout();
    router.replace("/login");
  }

  const filteredClients = clients.filter((c) =>
    c.name.toLowerCase().includes(searchQuery.toLowerCase()),
  );

  const totalCards = clients.reduce((acc, c) => acc + c.cards_count, 0);
  const totalNeeds = clients.reduce((acc, c) => acc + c.needs_count, 0);
  const totalRisks = clients.reduce((acc, c) => acc + c.risks_count, 0);

  return (
    <DashboardTemplate
      sidebar={
        <Sidebar
          user={user}
          workspaces={workspaces}
          selectedId={selectedWorkspace?.id ?? null}
          onSelectWorkspace={handleSelectWorkspace}
          onLogout={handleLogout}
        />
      }
    >
      <div className="mx-auto max-w-6xl space-y-8 p-6 md:p-8">
        {/* Header */}
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-indigo-50 px-3 py-1 text-xs font-semibold text-indigo-700">
              <Users className="h-3.5 w-3.5" />
              Phase 5: Client Intelligence Profiles
            </div>
            <h1 className="mt-2 text-2xl font-bold tracking-tight text-zinc-900 md:text-3xl">
              Client Dossiers & Overview
            </h1>
            <p className="mt-1 text-sm text-zinc-500">
              Deep, synthesized intelligence profiles across all your clients. Track verified needs,
              operational risks, key stakeholders, and activity timelines.
            </p>
          </div>

          <Button
            onClick={() => setIsModalOpen(true)}
            className="inline-flex h-11 items-center gap-2 rounded-xl bg-indigo-600 px-5 font-semibold text-white shadow-sm hover:bg-indigo-700"
          >
            <Plus className="h-4 w-4" />
            Add Client
          </Button>
        </div>

        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Aggregate KPI Strip */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <Building2 className="h-4 w-4 text-zinc-400" />
              Total Clients
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-900">{clients.length}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <CreditCard className="h-4 w-4 text-zinc-400" />
              Mapped Project Cards
            </div>
            <p className="mt-2 text-2xl font-bold text-zinc-900">{totalCards.toLocaleString()}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <Sparkles className="h-4 w-4 text-indigo-500" />
              Synthesized Needs
            </div>
            <p className="mt-2 text-2xl font-bold text-indigo-600">{totalNeeds.toLocaleString()}</p>
          </div>

          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm">
            <div className="flex items-center gap-2 text-xs font-medium text-zinc-500">
              <ShieldAlert className="h-4 w-4 text-rose-500" />
              Active Delivery Risks
            </div>
            <p className="mt-2 text-2xl font-bold text-rose-600">{totalRisks.toLocaleString()}</p>
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search clients by name…"
              className="h-10 w-full rounded-xl border border-zinc-200 bg-white pl-10 pr-4 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="text-xs text-zinc-500">
            Showing {filteredClients.length} of {clients.length} clients
          </div>
        </div>

        {/* Clients Grid */}
        {loading ? (
          <div className="flex h-64 items-center justify-center rounded-2xl border border-zinc-200 bg-white">
            <div className="flex items-center gap-2 text-zinc-500">
              <LoaderCircle className="h-5 w-5 animate-spin" />
              Loading client dossiers…
            </div>
          </div>
        ) : filteredClients.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 bg-white p-12 text-center">
            <Building2 className="mx-auto h-12 w-12 text-zinc-300" />
            <h3 className="mt-4 text-base font-semibold text-zinc-900">
              {searchQuery ? "No matching clients found" : "No clients created yet"}
            </h3>
            <p className="mt-1 text-sm text-zinc-500 max-w-sm mx-auto">
              {searchQuery
                ? "Try searching for a different name or clear the search query."
                : "Map your Trello boards or Jira projects by client, or click 'Add Client' to establish your first client profile."}
            </p>
            {!searchQuery && (
              <Button
                onClick={() => setIsModalOpen(true)}
                className="mt-5 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-700"
              >
                <Plus className="h-4 w-4" />
                Add First Client
              </Button>
            )}
          </div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {filteredClients.map((client) => {
              const hasHighRisks = client.risks_count > 0;
              return (
                <div
                  key={client.id}
                  className="group relative flex flex-col justify-between rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm transition-all hover:border-indigo-300 hover:shadow-md"
                >
                  <div>
                    {/* Header: Name & Risk Badge */}
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-700 font-bold text-white shadow-sm">
                          {client.name.trim().charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <h3 className="font-bold text-zinc-900 group-hover:text-indigo-600 transition-colors line-clamp-1">
                            {client.name}
                          </h3>
                          <p className="text-xs text-zinc-400">
                            Added {new Date(client.created_at).toLocaleDateString()}
                          </p>
                        </div>
                      </div>

                      {hasHighRisks ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2.5 py-0.5 text-xs font-medium text-rose-700 border border-rose-200">
                          <AlertTriangle className="h-3 w-3 text-rose-600" />
                          {client.risks_count} {client.risks_count === 1 ? "Risk" : "Risks"}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-200">
                          <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                          Healthy
                        </span>
                      )}
                    </div>

                    {/* Metrics Row */}
                    <div className="mt-5 grid grid-cols-3 gap-2 border-y border-zinc-100 py-3.5 text-center">
                      <div>
                        <span className="block text-xs text-zinc-400">Cards</span>
                        <span className="mt-0.5 block text-base font-bold text-zinc-800">
                          {client.cards_count}
                        </span>
                      </div>
                      <div>
                        <span className="block text-xs text-zinc-400">Needs</span>
                        <span className="mt-0.5 block text-base font-bold text-indigo-600">
                          {client.needs_count}
                        </span>
                      </div>
                      <div>
                        <span className="block text-xs text-zinc-400">Insights</span>
                        <span className="mt-0.5 block text-base font-bold text-zinc-800">
                          {client.insights_count}
                        </span>
                      </div>
                    </div>

                    {/* Last Run Date */}
                    <p className="mt-3 text-xs text-zinc-400">
                      {client.last_run_at ? (
                        <>Last Analysis: {new Date(client.last_run_at).toLocaleDateString()}</>
                      ) : (
                        <>No analysis run executed yet</>
                      )}
                    </p>
                  </div>

                  {/* Action Link */}
                  <div className="mt-5 pt-2">
                    <Link
                      href={`/dashboard/clients/${client.id}`}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-50 py-2.5 text-xs font-semibold text-zinc-700 transition-colors hover:bg-indigo-600 hover:text-white"
                    >
                      View Profile & Dossier
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Create Client Modal */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl border border-zinc-100">
              <h3 className="text-lg font-bold text-zinc-900">Add New Client</h3>
              <p className="mt-1 text-xs text-zinc-500">
                Create a client dossier in this workspace to aggregate project cards, git commits,
                and intelligence reports.
              </p>

              <form onSubmit={handleCreateClient} className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-700">Client Name</label>
                  <input
                    type="text"
                    required
                    value={newClientName}
                    onChange={(e) => setNewClientName(e.target.value)}
                    placeholder="e.g. Acme Corp, Northwind Traders"
                    className="mt-1 h-10 w-full rounded-xl border border-zinc-200 px-3 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => setIsModalOpen(false)}
                    className="text-xs"
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={creating || !newClientName.trim()}
                    className="rounded-xl bg-indigo-600 px-4 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {creating ? "Creating…" : "Create Client"}
                  </Button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </DashboardTemplate>
  );
}
