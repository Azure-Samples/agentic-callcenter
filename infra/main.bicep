targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment that can be used as part of naming resource convention')
param environmentName string

@description('The current user ID, to assign RBAC permissions to')
param currentUserId string

// Main deployment parameters
param prefix string = 'dev'
@minLength(1)
@description('Primary location for all resources')
param location string

@minLength(1)
@description('Name of the Azure OpenAI resource')
param openAIName string

@minLength(1)
@description('Name of the Azure Resource Group where the OpenAI resource is located')
param openAIResourceGroupName string

@minLength(1)
@description('Email address to send approval requests to')
param emailRecipientAddress string

param runningOnGh string = ''

param embeddingModel string
param openAIModel string
param openAIWhisperModel string
param openAIWhisperVersion string
param openAIApiVersion string
param searchIndexName string

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

var uniqueId = uniqueString(rg.id)
var currentUserType = empty(runningOnGh) ? 'User' : 'ServicePrincipal'

module uami './uami.bicep' = {
  name: 'uami'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    location: location
  }
}

module appin './appin.bicep' = {
  name: 'appin'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    location: location
    userAssignedIdentityPrincipalId: uami.outputs.principalId
  }
}

module acrModule './acr.bicep' = {
  name: 'acr'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    location: location
  }
}

module cosmosdb './cosmos.bicep' = {
  name: 'cosmosdb'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    location: location
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    currentUserId: currentUserId
    currentUserType: currentUserType
  }
}

module logicapp './logicapp.bicep' = {
  name: 'logicapp'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityResourceId: uami.outputs.identityId
    location: location
    emailRecipientAddress: emailRecipientAddress
  }
}

module openAI './openAI.bicep' = {
  name: 'openAI'
  scope: resourceGroup(openAIResourceGroupName)
  params: {
    openAIName: openAIName
    userAssignedIdentityPrincipalId: uami.outputs.principalId
  }
}

module acs './acs.bicep' = {
  name: 'acs'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    userAssignedIdentityResourceId: uami.outputs.identityId
  }
}

module speech './speech.bicep' = {
  name: 'speech'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    acsIdentityPrincipalId: acs.outputs.acsIdentityId
    location: location
  }
}

module storage './storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    location: location
    currentUserId: currentUserId
    currentUserType: currentUserType
  }
}

module search 'search.bicep' = {
  name: 'search'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityPrincipalId: uami.outputs.principalId
    userAssignedIdentityResourceId: uami.outputs.identityId
    location: location
    currentUserId: currentUserId
    currentUserType: currentUserType
  }
}

module aca './aca.bicep' = {
  name: 'aca'
  scope: rg
  params: {
    uniqueId: uniqueId
    prefix: prefix
    userAssignedIdentityResourceId: uami.outputs.identityId
    containerRegistry: acrModule.outputs.acrName
    location: location
    logAnalyticsWorkspaceName: appin.outputs.logAnalyticsWorkspaceName
    applicationInsightsConnectionString: appin.outputs.applicationInsightsConnectionString
    cosmosDbContainer: cosmosdb.outputs.cosmosDbContainer
    cosmosDbDatabase: cosmosdb.outputs.cosmosDbDatabase
    cosmosDbEndpoint: cosmosdb.outputs.cosmosDbEndpoint
    openAiApiKey: '' // Force ManId, otherwise set openAI.listKeys().key1
    openAiEndpoint: openAI.outputs.openAIEndpoint
    speechServiceKey: speech.outputs.speechServiceKey
    userAssignedIdentityClientId: uami.outputs.clientId
    acsEndpoint: acs.outputs.acsEndpoint
    cognitiveServiceEndpoint: speech.outputs.speechServiceEndpoint
    serviceBusNamespaceFqdn: acs.outputs.sbNamespaceFQDN
    searchEndpoint: search.outputs.endpoint
    searchIndexName: searchIndexName
    approvalLogicAppUrl: logicapp.outputs.approveServiceUrl
    openTicketLogicAppUrl: logicapp.outputs.openTicketUrl
  }
}

// These outputs are copied by azd to .azure/<env name>/.env file
// post provision script will use these values, too
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_TENANT_ID string = subscription().tenantId
output AZURE_USER_ASSIGNED_IDENTITY_ID string = uami.outputs.identityId
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acrModule.outputs.acrEndpoint
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddingModel
output AZURE_OPENAI_EMBEDDING_MODEL string = embeddingModel
output AZURE_STORAGE_ENDPOINT string = storage.outputs.storageAccountEndpoint
output AZURE_STORAGE_CONNECTION_STRING string = 'ResourceId=/subscriptions/${subscription().subscriptionId}/resourceGroups/${rg.name}/providers/Microsoft.Storage/storageAccounts/${storage.outputs.storageAccountName}'
output AZURE_STORAGE_CONTAINER string = storage.outputs.storageContainerName
output AZURE_STORAGE_ACCOUNT_NAME string = storage.outputs.storageAccountName
output AZURE_STORAGE_TTS_CONTAINER string = storage.outputs.ttsAudioContainerName
output APPLICATIONINSIGHTS_CONNECTIONSTRING string = appin.outputs.applicationInsightsConnectionString
output COSMOSDB_ENDPOINT string = cosmosdb.outputs.cosmosDbEndpoint
output COSMOSDB_DATABASE string = cosmosdb.outputs.cosmosDbDatabase
output COSMOSDB_CONTAINER string = cosmosdb.outputs.cosmosDbContainer
output COSMOSDB_CONFIG_CONTAINER string = cosmosdb.outputs.cosmosDbConfigContainer
output ACS_ENDPOINT string = acs.outputs.acsEndpoint
output ACS_TOPIC_RESOURCE_ID string = acs.outputs.acsTopicId
output LOGIC_APPS_URL string = logicapp.outputs.approveServiceUrl
output OPENTICKET_LOGIC_APPS_URL string = logicapp.outputs.openTicketUrl
output AZURE_OPENAI_MODEL string = openAIModel
output AZURE_OPENAI_ENDPOINT string = openAI.outputs.openAIEndpoint
output AZURE_OPENAI_API_VERSION string = openAIApiVersion
output AZURE_SEARCH_ENDPOINT string = search.outputs.endpoint
output AZURE_SEARCH_INDEX_NAME string = searchIndexName
output AZURE_SEARCH_ADMIN_KEY string = search.outputs.adminKey
output AZURE_OPENAI_WHISPER_VERSION string = openAIWhisperVersion
output AZURE_OPENAI_WHISPER_ENDPOINT string = openAI.outputs.openAIEndpoint
output AZURE_OPENAI_WHISPER_DEPLOYMENT string = openAIWhisperModel
output SPEECH_KEY string = speech.outputs.speechServiceKey
output COGNITIVE_SERVICES_ENDPOINT string = speech.outputs.speechServiceEndpoint
output SPEECH_REGION string = location
output VOICE_WEBHOOK_URL string = 'https://${aca.outputs.voiceEndpoint}/api/call'
output VOICE_SUBSCRIPTION_NAME string = '${prefix}-call-sub-${uniqueId}'
