---
name: agent-gateway
description: >
  Centralized gateway for managing multiple AI agents — providers, budgets, rate
  limits, and observability. Use when you have many agents calling many LLM
  providers and need to control cost, throttle traffic, and aggregate metrics.
  Derived from agentgateway (Apache-2.0).
version: 1.0.0
author: Alberto AI (from agentgateway)
license: Apache-2.0
metadata:
  alberto:
    category: ops
    tags: [gateway, multi-agent, budget, rate-limit, observability]
    upstream: https://github.com/agentgateway/agentgateway
---

# Agent Gateway

A gateway sits in front of multiple LLM providers and agents, providing:
- Unified OpenAI-compatible endpoint
- Per-agent budget caps (max cost per hour)
- Rate limiting (requests/min)
- Provider failover
- Log aggregation
- Cost dashboards

## Alberto integration

The Alberto `alberto serve` already exposes a unified endpoint. To add gateway
features to your own multi-agent setup, copy `examples/basic/gateway.yaml` into
your project and customize the agent definitions.

## When to use

- You run many agents calling many providers
- You need budget control (don't blow $10k in a weekend)
- You need to throttle runaway agents
- You need observability (logs + dashboards)
