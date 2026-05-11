import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { Ticket } from "@/types/ticket";

export function useTickets(params?: { airline_id?: number; supplier_id?: number }) {
  return useQuery({
    queryKey: ["tickets", params],
    queryFn: async () => {
      const { data } = await api.get<Ticket[]>("/tickets", { params });
      return data;
    },
  });
}

export function useUploadTickets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.post("/tickets/upload", form, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tickets"] }),
  });
}

export function useMatchTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ticketId, dealId }: { ticketId: number; dealId: number }) =>
      api.patch(`/tickets/${ticketId}/match`, null, { params: { deal_id: dealId } }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tickets"] });
      qc.invalidateQueries({ queryKey: ["income"] });
    },
  });
}
