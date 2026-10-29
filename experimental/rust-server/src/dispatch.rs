//! Common dispatch for both encrypted HTTP and the isolated differential probe.
use crate::{
    error::{Error, Result},
    state::State,
    wire::Request,
};

pub fn routes() -> Vec<&'static str> {
    let mut routes = crate::character::ROUTES.to_vec();
    routes.extend_from_slice(crate::services::ROUTES);
    routes.extend_from_slice(crate::lifecycle::ROUTES);
    routes.sort_unstable();
    routes.dedup();
    routes
}
pub fn dispatch(
    state: &State,
    route: &str,
    plaintext: &str,
    actor: Option<&str>,
) -> Result<String> {
    if !routes().contains(&route) {
        return Err(Error::new(501, "Route behavior has not been reconstructed"));
    }
    let request = Request::parse(
        plaintext,
        if route == "N2SavePreset" {
            Some(4)
        } else {
            None
        },
    )?;
    let result = if let Some(reply) = crate::character::handle_as(state, route, &request, actor)? {
        reply
    } else if let Some(reply) = crate::services::handle_as(state, route, &request, actor)? {
        reply
    } else if let Some(reply) = crate::lifecycle::handle_as(state, route, &request, actor)? {
        reply
    } else {
        return Err(Error::new(501, "Route behavior has not been reconstructed"));
    };
    if !result.contains('#')
        && !(route == "GetInfoServlet" && request.fields.first().is_some_and(|s| s == "0"))
    {
        return Err(Error::new(500, "Invalid shared sender response framing"));
    }
    Ok(result)
}
