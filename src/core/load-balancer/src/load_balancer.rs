use crate::strategies::strategy::ServerSelectionStrategy;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use hyper::{Body, Client, Request, Response, Uri};
use hyper::service::{make_service_fn, service_fn};
use http::{HeaderMap, HeaderValue};

pub struct LoadBalancer {
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
    request_counter: Arc<AtomicU64>,
}

impl LoadBalancer {
    pub fn new(servers: Vec<String>, strategy: Arc<dyn ServerSelectionStrategy>) -> Self {
        let mut counts = HashMap::new();
        for s in &servers {
            counts.insert(s.clone(), 0u64);
        }

        Self { 
            servers, 
            strategy,
            request_counter: Arc::new(AtomicU64::new(0)),
        }
    }

    pub async fn start(&self, bind_address: &str) -> Result<(), Box<dyn std::error::Error>> {
        let addr: SocketAddr = bind_address.parse()?;
        println!("HTTP load balancer listening on {}", bind_address);
        println!("Available servers: {:?}", self.servers);

        let servers = self.servers.clone();
        let strategy = Arc::clone(&self.strategy);
        let request_counter = Arc::clone(&self.request_counter);

        // Shared HTTP client for outbound requests
        let client: Client<hyper::client::HttpConnector, Body> = Client::new();
        let client = Arc::new(client);

        let make_svc = make_service_fn(move |_conn| {
            let servers = servers.clone();
            let strategy = Arc::clone(&strategy);
            let request_counter = Arc::clone(&request_counter);
            let client = Arc::clone(&client);

            async move {
                Ok::<_, hyper::Error>(service_fn(move |req: Request<Body>| {
                    let servers = servers.clone();
                    let strategy = Arc::clone(&strategy);
                    let request_counter = Arc::clone(&request_counter);
                    let client = Arc::clone(&client);

                    async move {
                        // Increment per-request counter
                        let _ = request_counter.fetch_add(1, Ordering::Relaxed);

                        // Pick backend per HTTP request
                        let backend = match strategy.pick_server(&servers) {
                            Some(s) => s,
                            None => {
                                return Ok::<_, hyper::Error>(response_with_status(
                                    http::StatusCode::BAD_GATEWAY,
                                    "No available servers",
                                ));
                            }
                        };
                        // if let Some(snapshot) = strategy.debug_snapshot() {
                        //     println!("Scores snapshot: {}", snapshot);
                        // }
                        // println!("Picking backend for request: {}", backend);
                        
                        // Build new URI with backend authority
                        let path_and_query = req
                            .uri()
                            .path_and_query()
                            .map(|pq| pq.as_str().to_string())
                            .unwrap_or_else(|| "/".to_string());

                        let new_uri: Uri = match Uri::builder()
                            .scheme("http")
                            .authority(backend.as_str())
                            .path_and_query(path_and_query.as_str())
                            .build() {
                                Ok(u) => u,
                                Err(_) => {
                                    return Ok::<_, hyper::Error>(response_with_status(
                                        http::StatusCode::BAD_GATEWAY,
                                        "Invalid backend URI",
                                    ));
                                }
                            };

                        // Rewrite request to target backend
                        let (mut parts, body) = req.into_parts();
                        parts.uri = new_uri;
                        sanitize_hop_by_hop_headers(&mut parts.headers);
                        parts.headers.insert(
                            http::header::HOST,
                            HeaderValue::from_str(backend.as_str()).unwrap_or(HeaderValue::from_static("")),
                        );

                        let outbound_req = Request::from_parts(parts, body);

                        // Forward
                        match client.request(outbound_req).await {
                            Ok(mut resp) => {
                                sanitize_hop_by_hop_headers(resp.headers_mut());
                                Ok::<_, hyper::Error>(resp)
                            }
                            Err(_e) => {
                                Ok::<_, hyper::Error>(response_with_status(
                                    http::StatusCode::BAD_GATEWAY,
                                    "Upstream request failed",
                                ))
                            }
                        }
                    }
                }))
            }
        });

        hyper::Server::bind(&addr).serve(make_svc).await?;
        Ok(())
    }
}

fn sanitize_hop_by_hop_headers(headers: &mut HeaderMap) {
    // Remove hop-by-hop headers per RFC 7230
    static HOP_HEADERS: &[&str] = &[
        "connection",
        "proxy-connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
    ];
    for name in HOP_HEADERS {
        headers.remove(*name);
    }
}

fn response_with_status(status: http::StatusCode, msg: &str) -> Response<Body> {
    Response::builder()
        .status(status)
        .header(http::header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(Body::from(msg.to_string()))
        .unwrap_or_else(|_| Response::new(Body::from(msg.to_string())))
}
