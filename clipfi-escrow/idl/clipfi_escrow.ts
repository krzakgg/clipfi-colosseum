/**
 * Program IDL in camelCase format in order to be used in JS/TS.
 *
 * Note that this is only a type helper and is not the actual IDL. The original
 * IDL can be found at `target/idl/clipfi_escrow.json`.
 */
export type ClipfiEscrow = {
  "address": "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx",
  "metadata": {
    "name": "clipfiEscrow",
    "version": "0.1.0",
    "spec": "0.1.0",
    "description": "ClipFi campaign escrow"
  },
  "instructions": [
    {
      "name": "closeCampaign",
      "discriminator": [
        65,
        49,
        110,
        7,
        63,
        238,
        206,
        77
      ],
      "accounts": [
        {
          "name": "brand",
          "writable": true,
          "signer": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "config",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  111,
                  110,
                  102,
                  105,
                  103
                ]
              }
            ]
          }
        },
        {
          "name": "campaign",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  109,
                  112,
                  97,
                  105,
                  103,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "brand"
              },
              {
                "kind": "account",
                "path": "campaign.campaign_id",
                "account": "campaign"
              }
            ]
          }
        },
        {
          "name": "mint",
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "vault",
          "writable": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "brandToken",
          "writable": true
        },
        {
          "name": "tokenProgram"
        }
      ],
      "args": []
    },
    {
      "name": "createCampaign",
      "discriminator": [
        111,
        131,
        187,
        98,
        160,
        193,
        114,
        244
      ],
      "accounts": [
        {
          "name": "brand",
          "writable": true,
          "signer": true
        },
        {
          "name": "config",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  111,
                  110,
                  102,
                  105,
                  103
                ]
              }
            ]
          }
        },
        {
          "name": "mint",
          "relations": [
            "config"
          ]
        },
        {
          "name": "campaign",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  109,
                  112,
                  97,
                  105,
                  103,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "brand"
              },
              {
                "kind": "arg",
                "path": "campaignId"
              }
            ]
          }
        },
        {
          "name": "vault",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "account",
                "path": "campaign"
              },
              {
                "kind": "account",
                "path": "tokenProgram"
              },
              {
                "kind": "account",
                "path": "mint"
              }
            ],
            "program": {
              "kind": "const",
              "value": [
                140,
                151,
                37,
                143,
                78,
                36,
                137,
                241,
                187,
                61,
                16,
                41,
                20,
                142,
                13,
                131,
                11,
                90,
                19,
                153,
                218,
                255,
                16,
                132,
                4,
                142,
                123,
                216,
                219,
                233,
                248,
                89
              ]
            }
          }
        },
        {
          "name": "associatedTokenProgram",
          "address": "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
        },
        {
          "name": "tokenProgram"
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": [
        {
          "name": "campaignId",
          "type": "u64"
        },
        {
          "name": "params",
          "type": {
            "defined": {
              "name": "campaignParams"
            }
          }
        }
      ]
    },
    {
      "name": "flagPayout",
      "discriminator": [
        250,
        16,
        71,
        24,
        29,
        49,
        26,
        68
      ],
      "accounts": [
        {
          "name": "brand",
          "signer": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "campaign",
          "relations": [
            "payout"
          ]
        },
        {
          "name": "payout",
          "writable": true
        }
      ],
      "args": [
        {
          "name": "reason",
          "type": "u16"
        }
      ]
    },
    {
      "name": "fundCampaign",
      "discriminator": [
        109,
        57,
        56,
        239,
        99,
        111,
        221,
        121
      ],
      "accounts": [
        {
          "name": "brand",
          "signer": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "campaign",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  109,
                  112,
                  97,
                  105,
                  103,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "brand"
              },
              {
                "kind": "account",
                "path": "campaign.campaign_id",
                "account": "campaign"
              }
            ]
          }
        },
        {
          "name": "mint",
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "brandToken",
          "writable": true
        },
        {
          "name": "vault",
          "writable": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "tokenProgram"
        }
      ],
      "args": [
        {
          "name": "amount",
          "type": "u64"
        }
      ]
    },
    {
      "name": "initConfig",
      "discriminator": [
        23,
        235,
        115,
        232,
        168,
        96,
        1,
        231
      ],
      "accounts": [
        {
          "name": "admin",
          "writable": true,
          "signer": true
        },
        {
          "name": "mint"
        },
        {
          "name": "config",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  111,
                  110,
                  102,
                  105,
                  103
                ]
              }
            ]
          }
        },
        {
          "name": "program",
          "address": "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
        },
        {
          "name": "programData"
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": [
        {
          "name": "oracle",
          "type": "pubkey"
        },
        {
          "name": "arbiter",
          "type": "pubkey"
        },
        {
          "name": "vestingSecs",
          "type": "i64"
        }
      ]
    },
    {
      "name": "release",
      "discriminator": [
        253,
        249,
        15,
        206,
        28,
        127,
        193,
        241
      ],
      "accounts": [
        {
          "name": "cranker",
          "writable": true,
          "signer": true
        },
        {
          "name": "campaign",
          "writable": true,
          "relations": [
            "payout"
          ]
        },
        {
          "name": "mint",
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "vault",
          "writable": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "creator",
          "relations": [
            "payout"
          ]
        },
        {
          "name": "creatorToken",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "account",
                "path": "creator"
              },
              {
                "kind": "account",
                "path": "tokenProgram"
              },
              {
                "kind": "account",
                "path": "mint"
              }
            ],
            "program": {
              "kind": "const",
              "value": [
                140,
                151,
                37,
                143,
                78,
                36,
                137,
                241,
                187,
                61,
                16,
                41,
                20,
                142,
                13,
                131,
                11,
                90,
                19,
                153,
                218,
                255,
                16,
                132,
                4,
                142,
                123,
                216,
                219,
                233,
                248,
                89
              ]
            }
          }
        },
        {
          "name": "position",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  112,
                  111,
                  115,
                  105,
                  116,
                  105,
                  111,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "campaign"
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "payout",
          "writable": true
        },
        {
          "name": "rentPayer",
          "writable": true,
          "relations": [
            "payout"
          ]
        },
        {
          "name": "associatedTokenProgram",
          "address": "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
        },
        {
          "name": "tokenProgram"
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": []
    },
    {
      "name": "resolve",
      "discriminator": [
        246,
        150,
        236,
        206,
        108,
        63,
        58,
        10
      ],
      "accounts": [
        {
          "name": "arbiter",
          "signer": true,
          "relations": [
            "config"
          ]
        },
        {
          "name": "config",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  111,
                  110,
                  102,
                  105,
                  103
                ]
              }
            ]
          }
        },
        {
          "name": "campaign",
          "writable": true,
          "relations": [
            "payout"
          ]
        },
        {
          "name": "position",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  112,
                  111,
                  115,
                  105,
                  116,
                  105,
                  111,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "campaign"
              },
              {
                "kind": "account",
                "path": "payout.creator",
                "account": "payout"
              }
            ]
          }
        },
        {
          "name": "payout",
          "writable": true
        },
        {
          "name": "rentPayer",
          "writable": true,
          "relations": [
            "payout"
          ]
        }
      ],
      "args": [
        {
          "name": "approve",
          "type": "bool"
        }
      ]
    },
    {
      "name": "settle",
      "discriminator": [
        175,
        42,
        185,
        87,
        144,
        131,
        102,
        212
      ],
      "accounts": [
        {
          "name": "oracle",
          "writable": true,
          "signer": true,
          "relations": [
            "config"
          ]
        },
        {
          "name": "config",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  111,
                  110,
                  102,
                  105,
                  103
                ]
              }
            ]
          }
        },
        {
          "name": "campaign",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  99,
                  97,
                  109,
                  112,
                  97,
                  105,
                  103,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "campaign.brand",
                "account": "campaign"
              },
              {
                "kind": "account",
                "path": "campaign.campaign_id",
                "account": "campaign"
              }
            ]
          }
        },
        {
          "name": "creator"
        },
        {
          "name": "position",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  112,
                  111,
                  115,
                  105,
                  116,
                  105,
                  111,
                  110
                ]
              },
              {
                "kind": "account",
                "path": "campaign"
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "payout",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  112,
                  97,
                  121,
                  111,
                  117,
                  116
                ]
              },
              {
                "kind": "account",
                "path": "campaign"
              },
              {
                "kind": "account",
                "path": "creator"
              },
              {
                "kind": "arg",
                "path": "epoch"
              }
            ]
          }
        },
        {
          "name": "systemProgram",
          "address": "11111111111111111111111111111111"
        }
      ],
      "args": [
        {
          "name": "epoch",
          "type": "u64"
        },
        {
          "name": "units",
          "type": {
            "array": [
              "u64",
              4
            ]
          }
        },
        {
          "name": "evidenceHash",
          "type": {
            "array": [
              "u8",
              32
            ]
          }
        }
      ]
    }
  ],
  "accounts": [
    {
      "name": "campaign",
      "discriminator": [
        50,
        40,
        49,
        11,
        157,
        220,
        229,
        192
      ]
    },
    {
      "name": "config",
      "discriminator": [
        155,
        12,
        170,
        224,
        30,
        250,
        204,
        130
      ]
    },
    {
      "name": "creatorPosition",
      "discriminator": [
        6,
        206,
        125,
        34,
        174,
        236,
        166,
        81
      ]
    },
    {
      "name": "payout",
      "discriminator": [
        69,
        45,
        245,
        131,
        218,
        101,
        158,
        228
      ]
    }
  ],
  "events": [
    {
      "name": "campaignClosed",
      "discriminator": [
        158,
        143,
        128,
        251,
        84,
        131,
        2,
        90
      ]
    },
    {
      "name": "campaignCreated",
      "discriminator": [
        9,
        98,
        69,
        61,
        53,
        131,
        64,
        152
      ]
    },
    {
      "name": "campaignFunded",
      "discriminator": [
        46,
        83,
        210,
        201,
        110,
        227,
        24,
        212
      ]
    },
    {
      "name": "payoutFlagged",
      "discriminator": [
        192,
        90,
        167,
        42,
        201,
        53,
        230,
        10
      ]
    },
    {
      "name": "payoutReleased",
      "discriminator": [
        245,
        195,
        37,
        2,
        200,
        70,
        126,
        210
      ]
    },
    {
      "name": "payoutResolved",
      "discriminator": [
        224,
        55,
        196,
        114,
        199,
        46,
        228,
        240
      ]
    },
    {
      "name": "settled",
      "discriminator": [
        232,
        210,
        40,
        17,
        142,
        124,
        145,
        238
      ]
    }
  ],
  "errors": [
    {
      "code": 6000,
      "name": "invalidVesting",
      "msg": "vesting must be between 1 second and 21 days"
    },
    {
      "code": 6001,
      "name": "invalidWindow",
      "msg": "campaign must end after it starts and after now"
    },
    {
      "code": 6002,
      "name": "invalidRates",
      "msg": "at least one rate must be above zero"
    },
    {
      "code": 6003,
      "name": "invalidLimit",
      "msg": "limit per creator must be above zero"
    },
    {
      "code": 6004,
      "name": "zeroAmount",
      "msg": "amount must be above zero"
    },
    {
      "code": 6005,
      "name": "campaignClosed",
      "msg": "campaign is closed"
    },
    {
      "code": 6006,
      "name": "overflow",
      "msg": "arithmetic overflow"
    },
    {
      "code": 6007,
      "name": "underflow",
      "msg": "arithmetic underflow"
    },
    {
      "code": 6008,
      "name": "notStarted",
      "msg": "campaign has not started yet"
    },
    {
      "code": 6009,
      "name": "epochAlreadySettled",
      "msg": "this epoch or a later one is already settled for the creator"
    },
    {
      "code": 6010,
      "name": "nothingToSettle",
      "msg": "nothing to pay: no units, creator limit reached or budget used up"
    },
    {
      "code": 6011,
      "name": "payoutNotPending",
      "msg": "payout is not pending"
    },
    {
      "code": 6012,
      "name": "flagWindowClosed",
      "msg": "payout can only be flagged before it unlocks"
    },
    {
      "code": 6013,
      "name": "payoutNotFlagged",
      "msg": "payout is not flagged"
    },
    {
      "code": 6014,
      "name": "payoutFrozen",
      "msg": "payout is flagged and waits for the arbiter"
    },
    {
      "code": 6015,
      "name": "stillVesting",
      "msg": "payout is still vesting"
    },
    {
      "code": 6016,
      "name": "campaignStillRunning",
      "msg": "campaign can be closed only after its end plus the vesting period"
    },
    {
      "code": 6017,
      "name": "payoutsOutstanding",
      "msg": "campaign still has payouts that are not released or cancelled"
    },
    {
      "code": 6018,
      "name": "unsupportedMint",
      "msg": "mint is not supported: transfer-fee extension would desync the vault from the ledger"
    },
    {
      "code": 6019,
      "name": "unauthorized",
      "msg": "only the program upgrade authority may initialize the config"
    }
  ],
  "types": [
    {
      "name": "campaign",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "brand",
            "type": "pubkey"
          },
          {
            "name": "campaignId",
            "type": "u64"
          },
          {
            "name": "mint",
            "type": "pubkey"
          },
          {
            "name": "vault",
            "type": "pubkey"
          },
          {
            "name": "fundedTotal",
            "type": "u64"
          },
          {
            "name": "reserved",
            "type": "u64"
          },
          {
            "name": "paidTotal",
            "type": "u64"
          },
          {
            "name": "ratePerMille",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "maxPerCreator",
            "type": "u64"
          },
          {
            "name": "startTs",
            "type": "i64"
          },
          {
            "name": "endTs",
            "type": "i64"
          },
          {
            "name": "standardsHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "status",
            "type": {
              "defined": {
                "name": "campaignStatus"
              }
            }
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "campaignClosed",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "refunded",
            "type": "u64"
          },
          {
            "name": "paidTotal",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "campaignCreated",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "brand",
            "type": "pubkey"
          },
          {
            "name": "campaignId",
            "type": "u64"
          },
          {
            "name": "vault",
            "type": "pubkey"
          },
          {
            "name": "startTs",
            "type": "i64"
          },
          {
            "name": "endTs",
            "type": "i64"
          }
        ]
      }
    },
    {
      "name": "campaignFunded",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "fundedTotal",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "campaignParams",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "ratePerMille",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "maxPerCreator",
            "type": "u64"
          },
          {
            "name": "startTs",
            "type": "i64"
          },
          {
            "name": "endTs",
            "type": "i64"
          },
          {
            "name": "standardsHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          }
        ]
      }
    },
    {
      "name": "campaignStatus",
      "type": {
        "kind": "enum",
        "variants": [
          {
            "name": "active"
          },
          {
            "name": "closed"
          }
        ]
      }
    },
    {
      "name": "config",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "admin",
            "type": "pubkey"
          },
          {
            "name": "oracle",
            "type": "pubkey"
          },
          {
            "name": "arbiter",
            "type": "pubkey"
          },
          {
            "name": "mint",
            "type": "pubkey"
          },
          {
            "name": "vestingSecs",
            "type": "i64"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "creatorPosition",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "earnedTotal",
            "type": "u64"
          },
          {
            "name": "claimedTotal",
            "type": "u64"
          },
          {
            "name": "lastEpoch",
            "type": "u64"
          },
          {
            "name": "unitsTotal",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "payout",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "epoch",
            "type": "u64"
          },
          {
            "name": "units",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "evidenceHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "unlockTs",
            "type": "i64"
          },
          {
            "name": "status",
            "type": {
              "defined": {
                "name": "payoutStatus"
              }
            }
          },
          {
            "name": "rentPayer",
            "type": "pubkey"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "payoutFlagged",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "epoch",
            "type": "u64"
          },
          {
            "name": "reason",
            "type": "u16"
          }
        ]
      }
    },
    {
      "name": "payoutReleased",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "epoch",
            "type": "u64"
          },
          {
            "name": "amount",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "payoutResolved",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "epoch",
            "type": "u64"
          },
          {
            "name": "approved",
            "type": "bool"
          },
          {
            "name": "amount",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "payoutStatus",
      "type": {
        "kind": "enum",
        "variants": [
          {
            "name": "pending"
          },
          {
            "name": "flagged"
          },
          {
            "name": "approved"
          }
        ]
      }
    },
    {
      "name": "settled",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "epoch",
            "type": "u64"
          },
          {
            "name": "units",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "unlockTs",
            "type": "i64"
          },
          {
            "name": "evidenceHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          }
        ]
      }
    }
  ]
};
