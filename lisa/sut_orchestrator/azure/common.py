# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import re
from dataclasses import InitVar, dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from azure.mgmt.compute import ComputeManagementClient  # type: ignore
from azure.mgmt.marketplaceordering import MarketplaceOrderingAgreements  # type: ignore
from azure.mgmt.network import NetworkManagementClient  # type: ignore
from azure.mgmt.storage import StorageManagementClient  # type: ignore
from dataclasses_json import dataclass_json

from lisa import schema
from lisa.environment import Environment
from lisa.node import Node
from lisa.util import LisaException

if TYPE_CHECKING:
    from .platform_ import AzurePlatform

AZURE = "azure"


@dataclass
class EnvironmentContext:
    resource_group_name: str = ""
    resource_group_is_created: bool = False


@dataclass
class NodeContext:
    resource_group_name: str = ""
    vm_name: str = ""
    username: str = ""
    password: str = ""
    private_key_file: str = ""


@dataclass_json()
@dataclass
class AzureVmPurchasePlanSchema:
    name: str
    product: str
    publisher: str


@dataclass_json()
@dataclass
class AzureVmMarketplaceSchema:
    publisher: str = "Canonical"
    offer: str = "UbuntuServer"
    sku: str = "18.04-LTS"
    version: str = "Latest"


@dataclass_json()
@dataclass
class AzureNodeSchema:
    name: str = ""
    vm_size: str = ""
    location: str = ""
    marketplace_raw: Optional[Union[Dict[Any, Any], str]] = field(
        default=None, metadata=schema.metadata(data_key="marketplace")
    )
    vhd: str = ""
    nic_count: int = 1
    # for marketplace image, which need to accept terms
    purchase_plan: Optional[AzureVmPurchasePlanSchema] = None

    _marketplace: InitVar[Optional[AzureVmMarketplaceSchema]] = None

    @property
    def marketplace(self) -> Optional[AzureVmMarketplaceSchema]:
        # this is a safe guard and prevent mypy error on typing
        if not hasattr(self, "_marketplace"):
            self._marketplace: Optional[AzureVmMarketplaceSchema] = None
        marketplace: Optional[AzureVmMarketplaceSchema] = self._marketplace
        if not marketplace:
            if isinstance(self.marketplace_raw, dict):
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                self.marketplace_raw = dict(
                    (k, v.lower()) for k, v in self.marketplace_raw.items()
                )
                marketplace = AzureVmMarketplaceSchema.schema().load(  # type: ignore
                    self.marketplace_raw
                )
                # this step makes marketplace_raw is validated, and
                # filter out any unwanted content.
                self.marketplace_raw = marketplace.to_dict()  # type: ignore
            elif self.marketplace_raw:
                assert isinstance(
                    self.marketplace_raw, str
                ), f"actual: {type(self.marketplace_raw)}"
                # Users decide the cases of image names,
                #  the inconsistent cases cause the mismatched error in notifiers.
                # The lower() normalizes the image names,
                #  it has no impact on deployment.
                marketplace_strings = re.split(
                    r"[:\s]+", self.marketplace_raw.strip().lower()
                )

                if len(marketplace_strings) == 4:
                    marketplace = AzureVmMarketplaceSchema(*marketplace_strings)
                    # marketplace_raw is used
                    self.marketplace_raw = marketplace.to_dict()  # type: ignore
                else:
                    raise LisaException(
                        f"Invalid value for the provided marketplace "
                        f"parameter: '{self.marketplace_raw}'."
                        f"The marketplace parameter should be in the format: "
                        f"'<Publisher> <Offer> <Sku> <Version>' "
                        f"or '<Publisher>:<Offer>:<Sku>:<Version>'"
                    )
            self._marketplace = marketplace
        return marketplace

    @marketplace.setter
    def marketplace(self, value: Optional[AzureVmMarketplaceSchema]) -> None:
        self._marketplace = value
        if value is None:
            self.marketplace_raw = None
        else:
            self.marketplace_raw = value.to_dict()  # type: ignore

    def get_image_name(self) -> str:
        result = ""
        if self.vhd:
            result = self.vhd
        elif self.marketplace:
            assert isinstance(
                self.marketplace_raw, dict
            ), f"actual type: {type(self.marketplace_raw)}"
            result = " ".join([x for x in self.marketplace_raw.values()])
        return result


def get_compute_client(platform: Any) -> ComputeManagementClient:
    # there is cycle import, if assert type.
    # so it just use typing here only, no assertion.
    azure_platform: AzurePlatform = platform
    return ComputeManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_network_client(platform: Any) -> ComputeManagementClient:
    # there is cycle import, if assert type.
    # so it just use typing here only, no assertion.
    azure_platform: AzurePlatform = platform
    return NetworkManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_storage_client(platform: Any) -> ComputeManagementClient:
    azure_platform: AzurePlatform = platform
    return StorageManagementClient(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_storage_account_name(subscription_id: str, location: str) -> str:
    subscription_id_postfix = subscription_id[-8:]
    # name should be shorter than 24 charactor
    return f"lisas{location[0:11]}{subscription_id_postfix}"


def get_marketplace_ordering_client(platform: Any) -> MarketplaceOrderingAgreements:
    azure_platform: AzurePlatform = platform
    return MarketplaceOrderingAgreements(
        credential=azure_platform.credential,
        subscription_id=azure_platform.subscription_id,
    )


def get_node_context(node: Node) -> NodeContext:
    return node.get_context(NodeContext)


def get_environment_context(environment: Environment) -> EnvironmentContext:
    return environment.get_context(EnvironmentContext)


def wait_operation(operation: Any) -> Any:
    # to support timeout in future
    return operation.wait()
