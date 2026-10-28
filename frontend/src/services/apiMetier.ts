import type { components, operations, paths } from "@/types/api/api-metier";
import { createApiClient, unwrap, type JsonBody, type Query } from "./client";

// API métier : authentification et comptes (contracts/openapi/api-metier.openapi.yaml).
export type User = components["schemas"]["User"];
export type Role = components["schemas"]["Role"];
const client = createApiClient<paths>();

export async function login(credentials: JsonBody<operations["login"]>) {
  return unwrap(await client.POST("/api/v1/auth/login", { body: credentials }));
}

export async function getCurrentUser() {
  return unwrap(await client.GET("/api/v1/auth/me"));
}

export async function listUsers(query?: Query<operations["listUsers"]>) {
  return unwrap(await client.GET("/api/v1/users", { params: { query } }));
}

export async function createUser(user: JsonBody<operations["createUser"]>) {
  return unwrap(await client.POST("/api/v1/users", { body: user }));
}

export async function getUser(userId: string) {
  return unwrap(
    await client.GET("/api/v1/users/{user_id}", { params: { path: { user_id: userId } } }),
  );
}

export async function updateUser(userId: string, changes: JsonBody<operations["updateUser"]>) {
  return unwrap(
    await client.PATCH("/api/v1/users/{user_id}", {
      params: { path: { user_id: userId } },
      body: changes,
    }),
  );
}
