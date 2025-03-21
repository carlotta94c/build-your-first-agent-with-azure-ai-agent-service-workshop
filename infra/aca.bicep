param name string
param location string = resourceGroup().location
param tags object = {}

param identityName string
param containerAppsEnvironmentName string
param containerRegistryName string
param serviceName string = 'aca'
param exists bool
param modelDeploymentName string
param projectConnectionString string
param allowedOrigins string = '' // comma separated list of allowed origins - no slash at the end!
param bingConnectionName string
@secure()
param chainlitAuthSecret string
@secure()
param literalApiKey string = ''
@secure()
param userPassword string

resource acaIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}


module app 'core/host/container-app-upsert.bicep' = {
  name: '${serviceName}-container-app-module'
  params: {
    name: name
    location: location
    tags: union(tags, { 'azd-service-name': serviceName })
    identityName: acaIdentity.name
    exists: exists
    containerAppsEnvironmentName: containerAppsEnvironmentName
    containerRegistryName: containerRegistryName
    containerCpuCoreCount: '0.25'
    containerMemory: '0.5Gi'
    containerMaxReplicas: 1
    secrets:[
      {
        name: 'model-deployment-name'
        value: modelDeploymentName
      }
      {
        name: 'project-connection-string'
        value: projectConnectionString
      }
      {
        name: 'chainlit-auth-secret'
        value: chainlitAuthSecret
      }
      {
        name: 'literal-api-key'
        value: literalApiKey
      }
      {
        name: 'user-password'
        value: userPassword
      }
      {
        name: 'bing-connection-name'
        value: bingConnectionName
      }
    ]
    env: [
      {
        name: 'MODEL_DEPLOYMENT_NAME'
        secretRef: 'model-deployment-name'
      }
      {
        name: 'PROJECT_CONNECTION_STRING'
        secretRef: 'project-connection-string'
      }
      {
        name: 'CHAINLIT_AUTH_SECRET'
        secretRef: 'chainlit-auth-secret'
      }
      {
        name: 'LITERAL_API_KEY'
        secretRef: 'literal-api-key'
      }
      {
        name: 'AGENT_PASSWORD'
        secretRef: 'user-password'
      }
      {
        name: 'ENV'
        value: 'production'
      }
      {
        name: 'ALLOWED_ORIGINS'
        value: allowedOrigins
      }
      {
        name: 'BING_CONNECTION_NAME'
        value: 'bing-connection-name'
      }
    ]
    targetPort: 80
  }
}

output SERVICE_ACA_IDENTITY_PRINCIPAL_ID string = acaIdentity.properties.principalId
output SERVICE_ACA_NAME string = app.outputs.name
output SERVICE_ACA_URI string = app.outputs.uri
output SERVICE_ACA_IMAGE_NAME string = app.outputs.imageName
