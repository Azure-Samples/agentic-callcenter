param uniqueId string
param prefix string
@secure()
param userAssignedIdentityPrincipalId string
param currentUserId string
param currentUserType string
param location string = resourceGroup().location

resource storageAccount 'Microsoft.Storage/storageAccounts@2021-04-01' = {
  name: '${prefix}sta${uniqueId}'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
  }
}
resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

// Container for the storage account
resource storageContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2021-04-01' = {
  name: 'documents'
  parent: blobServices
  properties: {
    publicAccess: 'None'
  }
}

// Container for TTS audio files (publicly accessible for Azure CallAutomation)
resource ttsAudioContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2021-04-01' = {
  name: 'tts-audio'
  parent: blobServices
  properties: {
    publicAccess: 'Blob'  // Allow public read access to individual blobs
  }
}

resource blobRoleAssignment 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(storageAccount.id, userAssignedIdentityPrincipalId, 'blobDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: userAssignedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource storageAccountContributorRoleAssignment 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(storageAccount.id, userAssignedIdentityPrincipalId, 'storageAccountContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '17d1049b-9a84-46fb-8f53-869881c3d3ab')
    principalId: userAssignedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}
resource blobRoleAssignmentUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(storageAccount.id, currentUserId, 'blobDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: currentUserId
    principalType: currentUserType
  }
}
resource storageAccountContributorRoleAssignmentUser 'Microsoft.Authorization/roleAssignments@2020-04-01-preview' = {
  name: guid(storageAccount.id, currentUserId, 'storageAccountContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: resourceId('Microsoft.Authorization/roleDefinitions', '17d1049b-9a84-46fb-8f53-869881c3d3ab')
    principalId: currentUserId
    principalType: currentUserType
  }
}

output storageAccountName string = storageAccount.name
output storageAccountEndpoint string = storageAccount.properties.primaryEndpoints.blob
#disable-next-line outputs-should-not-contain-secrets
output storageAccountConnectionString string = storageAccount.listKeys().keys[0].value
output storageContainerName string = storageContainer.name
output ttsAudioContainerName string = ttsAudioContainer.name
