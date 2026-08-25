import {
  createMcpPrincipal,
  type CreateMcpPrincipalInput,
  revokeMcpPrincipal,
  rotateMcpPrincipal,
} from "../../../domains/mcp/api/mcpApi";

export type CreateMcpPrincipalCommand = {
  adminToken: string;
  input: CreateMcpPrincipalInput;
};

export type RotateMcpPrincipalCommand = {
  adminToken: string;
  principalId: string;
};

export type RevokeMcpPrincipalCommand = RotateMcpPrincipalCommand;

export function createMcpPrincipalCommand(command: CreateMcpPrincipalCommand) {
  return createMcpPrincipal(command.adminToken, command.input);
}

export function rotateMcpPrincipalCommand(command: RotateMcpPrincipalCommand) {
  return rotateMcpPrincipal(command.adminToken, command.principalId);
}

export function revokeMcpPrincipalCommand(command: RevokeMcpPrincipalCommand) {
  return revokeMcpPrincipal(command.adminToken, command.principalId);
}
