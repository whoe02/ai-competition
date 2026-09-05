import type {
  Activity,
  BriefingInboxResponse,
  ButlerThread,
  Capture,
  CaptureAvailability,
  Category,
  DashboardToday,
  ForesightResponse,
  HindsightResponse,
  DayPlan,
  DayPlanAsk,
  DayPlanReading,
  Memory,
  PlanDraft,
  TokenResponse,
  Transaction,
  TransactionCorrection,
  UserResponse,
  FinancialProfileUpdate,
  GoalIncomeAllocation,
  AppliedGoalIncomeAllocation,
} from "@kira/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export const dashboardTodayKey = ["dashboard", "today"] as const;
export const activityKey = ["transactions"] as const;
export const foresightKey = ["foresight"] as const;
export const hindsightKey = ["hindsight"] as const;
export const briefingTodayKey = ["briefings", "today"] as const;
export const profileKey = ["auth", "me"] as const;
const activityKeyFor = (category: string | null) => [...activityKey, category] as const;

export function useDashboardToday(enabled: boolean) {
  return useQuery({
    queryKey: dashboardTodayKey,
    queryFn: () => api.get<DashboardToday>("/v1/dashboard/today"),
    enabled,
  });
}

export function useForesight(enabled: boolean, horizon?: number) {
  return useQuery({
    queryKey: [...foresightKey, horizon ?? "default"],
    queryFn: () =>
      api.get<ForesightResponse>(
        horizon === undefined ? "/v1/foresight" : `/v1/foresight?horizon=${horizon}`,
      ),
    enabled,
  });
}

export function useHindsight(enabled: boolean) {
  return useQuery({
    queryKey: hindsightKey,
    queryFn: () => api.get<HindsightResponse>("/v1/hindsight"),
    enabled,
  });
}

export function useBriefingToday(enabled: boolean) {
  return useQuery({
    queryKey: briefingTodayKey,
    queryFn: () => api.get<BriefingInboxResponse | null>("/v1/briefings/today"),
    enabled,
  });
}

export function useActivity(enabled: boolean, category: string | null = null) {
  return useQuery({
    queryKey: activityKeyFor(category),
    queryFn: () =>
      api.get<Activity>(
        category === null
          ? "/v1/transactions"
          : `/v1/transactions?category=${encodeURIComponent(category)}`,
      ),
    enabled,
    // The chips are the same on every filtered response, so the previous
    // ledger stays put while the next one loads instead of flashing empty.
    placeholderData: (previous) => previous,
  });
}

export type DayPlanParams = {
  lat: number;
  lng: number;
  mode: "walk" | "transit" | "ride";
  halalOnly: boolean;
  capSen?: number;
  /** One kind of food, or null for every kind. */
  kind?: string | null;
};

type DayPlanKey = readonly ["day-plan", DayPlanParams];

/** The ceiling only decides which of the same places are shown. Everything else
 *  in the search decides what the places are, how far away they are, and what
 *  they cost — so a previous answer may outlive a change of ceiling and nothing
 *  else. A kind of food is one of those others: the previous list is a list of
 *  different shops, and holding it under a chip that now says Noodles would be
 *  answering the new question with the old answer. */
function sameSearch(before: DayPlanParams, now: DayPlanParams): boolean {
  return (
    before.lat === now.lat &&
    before.lng === now.lng &&
    before.mode === now.mode &&
    before.halalOnly === now.halalOnly &&
    (before.kind ?? null) === (now.kind ?? null)
  );
}

export function useDayPlan(enabled: boolean, params: DayPlanParams) {
  const query = new URLSearchParams({
    lat: String(params.lat),
    lng: String(params.lng),
    mode: params.mode,
    halal_only: String(params.halalOnly),
    ...(params.capSen !== undefined ? { cap_sen: String(params.capSen) } : {}),
    ...(params.kind ? { kind: params.kind } : {}),
  });
  return useQuery({
    queryKey: ["day-plan", params] as DayPlanKey,
    queryFn: () => api.get<DayPlan>("/v1/day-plan/places?" + query),
    // Held back while the screen is still finding out where it is planning
    // from. A list fetched for the fallback in that gap would be a whole plan
    // on screen — its header, its distances and its fares — for somewhere the
    // user is not, and every figure on it would change the moment the device
    // answered.
    enabled,
    // The ceiling slider is part of this query's own key, so without this the
    // control unmounts into the loading state on its first step and the drag is
    // over before it began. Held across a change of origin or mode, though, the
    // same trick would put the old answer under the new question: distances and
    // fares measured from KLCC, sitting under a header that has already started
    // saying "Near you". Waiting is honest; that is not.
    placeholderData: (previous, previousQuery) => {
      const before = (previousQuery?.queryKey as DayPlanKey | undefined)?.[1];
      return before && sameSearch(before, params) ? previous : undefined;
    },
  });
}

/**
 * Read a sentence into the day planner's own controls.
 *
 * Not a query, and not a write either: nothing is stored, and the answer is
 * only worth having in reply to a sentence somebody just typed. It invalidates
 * nothing — the list re-fetches because the controls moved, through the same
 * `useDayPlan` key as a tapped chip, which is the point of the whole endpoint.
 * A hook that fetched its own places here would be a second list.
 */
export function useInterpretDayPlan() {
  return useMutation<DayPlanReading, Error, DayPlanAsk>({
    mutationFn: (ask) => api.post<DayPlanReading>("/v1/day-plan/interpret", ask),
  });
}

/**
 * A write that changes what the ledger and Today are showing, whichever screen
 * it was fired from.
 *
 * Both keys, always. A stale safe-to-spend after a confirm would be a wrong
 * number on screen, and Today also carries the count of drafts waiting — so
 * even a write that cannot move the money (adding a plan, correcting a draft)
 * still changes something Today is showing.
 */
function useLedgerWrite<TData, TVariables>(mutationFn: (variables: TVariables) => Promise<TData>) {
  const queryClient = useQueryClient();
  return useMutation<TData, Error, TVariables>({
    mutationFn,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: activityKey }),
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
      ]);
    },
  });
}

function useSettle(action: "confirm" | "discard" | "unconfirm") {
  return useLedgerWrite((id: string) => api.post<Transaction>(`/v1/transactions/${id}/${action}`));
}

export function useConfirmDraft() {
  return useSettle("confirm");
}

export function useDiscardDraft() {
  return useSettle("discard");
}

export function useUnconfirm() {
  return useSettle("unconfirm");
}

export function useIncomeGoalAllocation(transactionId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["transactions", transactionId, "goal-allocation"],
    queryFn: () =>
      api.get<GoalIncomeAllocation>(`/v1/transactions/${transactionId}/goal-allocation`),
    enabled: Boolean(transactionId) && enabled,
    retry: false,
  });
}

export function useApproveIncomeGoalAllocation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (transactionId: string) =>
      api.post<AppliedGoalIncomeAllocation>(
        `/v1/transactions/${transactionId}/goal-allocation/approve`,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: activityKey }),
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
        queryClient.invalidateQueries({ queryKey: ["goals"] }),
      ]);
    },
  });
}

/** What the user says a draft should have read. Anything left out stays as it is. */
export type Correction = { id: string } & TransactionCorrection;

/**
 * Correct a draft before it is counted. Drafts only — the API refuses the rest.
 *
 * A draft is not on the ledger, so this rarely moves Today's figure by itself —
 * but the corrected amount is the one the next confirm spends, and a hook that
 * re-read only the ledger would be the one path able to leave a safe-to-spend
 * on screen that was worked out from a figure the user has already overwritten.
 */
export function useCorrectDraft() {
  return useLedgerWrite(({ id, ...correction }: Correction) =>
    api.patch<Transaction>(`/v1/transactions/${id}`, correction),
  );
}

/**
 * Add a planned outing to today. It lands as a draft, like every other capture.
 *
 * The body is the place as the row showed it — the whole outing's price, and
 * the place's own confidence *band*. The date, the percentage that band is
 * worth and the note that says the money has not moved are all the server's,
 * so no client can restate them.
 *
 * Today's safe-to-spend does not change here and is refetched anyway: the count
 * of drafts waiting sits on the same response, and it has gone up by one.
 */
export function useAddPlanToToday() {
  return useLedgerWrite((outing: PlanDraft) =>
    api.post<Transaction>("/v1/day-plan/drafts", outing),
  );
}

export const butlerThreadKey = ["butler", "thread"] as const;
export const memoriesKey = ["butler", "memories"] as const;

export function useButlerThread(enabled: boolean) {
  return useQuery({
    queryKey: butlerThreadKey,
    queryFn: () => api.get<ButlerThread>("/v1/butler/thread"),
    enabled,
  });
}

export function useMemories(enabled: boolean) {
  return useQuery({
    queryKey: memoriesKey,
    queryFn: () => api.get<Memory[]>("/v1/butler/memories"),
    enabled,
  });
}

export function useCorrectMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fact }: { id: string; fact: string }) =>
      api.patch<Memory>(`/v1/butler/memories/${id}`, { fact }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memoriesKey }),
  });
}

export function useForgetMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/v1/butler/memories/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memoriesKey }),
  });
}

/** Whether the camera and microphone affordances should be offered at all. */
export function useCategories(enabled: boolean) {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/v1/categories"),
    enabled,
    staleTime: Infinity,
  });
}

export function useCaptureAvailability(enabled: boolean) {
  return useQuery({
    queryKey: ["capture"],
    queryFn: () => api.get<CaptureAvailability>("/v1/capture"),
    enabled,
    staleTime: Infinity,
  });
}

export function useReadCapture(kind: "receipt" | "voice") {
  return useMutation({
    mutationFn: (file: Blob) => {
      const form = new FormData();
      form.append(kind === "receipt" ? "image" : "audio", file, `capture.${kind}`);
      return api.upload<Capture>(`/v1/capture/${kind}`, form);
    },
  });
}

/**
 * Save what was read. It becomes a draft, which is not yet the ledger.
 *
 * `direction` defaults on the server, so a caller that only ever records
 * spending says nothing about it. Income must name its type: the API refuses an
 * income without one, and refuses an expense that has one.
 */
export function useCreateDraft() {
  return useLedgerWrite(
    (draft: {
      merchant: string;
      amount_sen: number;
      occurred_on: string;
      category?: string;
      source?: string;
      confidence?: number | null;
      note?: string;
      direction?: "expense" | "income";
      income_type?: "salary" | "other" | null;
    }) => api.post<Transaction>("/v1/transactions", draft),
  );
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<TokenResponse>("/v1/auth/login", credentials),
    onSuccess: (token) => {
      api.setAccessToken(token.access_token);
      void queryClient.invalidateQueries({ queryKey: dashboardTodayKey });
      void queryClient.invalidateQueries({ queryKey: activityKey });
      void queryClient.invalidateQueries({ queryKey: butlerThreadKey });
    },
  });
}

export function useFinancialProfile(enabled: boolean) {
  return useQuery({
    queryKey: profileKey,
    queryFn: () => api.get<UserResponse>("/v1/auth/me"),
    enabled,
  });
}

export function useUpdateFinancialProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: FinancialProfileUpdate) =>
      api.patch<UserResponse>("/v1/auth/me", profile),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: profileKey }),
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
        queryClient.invalidateQueries({ queryKey: ["goals"] }),
      ]);
    },
  });
}
