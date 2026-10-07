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
      "name": "fundBonusPool",
      "discriminator": [
        100,
        221,
        65,
        252,
        148,
        193,
        251,
        17
      ],
      "accounts": [
        {
          "name": "funder",
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
          "name": "bonusVault",
          "writable": true,
          "relations": [
            "config"
          ]
        },
        {
          "name": "funderToken",
          "writable": true
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
          "name": "bonusVault",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "account",
                "path": "config"
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
          "name": "program",
          "address": "GAXMVFUXzAPBwhW4cF127HiSZmiY791XX2mBFEqqBwx"
        },
        {
          "name": "programData"
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
          "name": "params",
          "type": {
            "defined": {
              "name": "configParams"
            }
          }
        }
      ]
    },
    {
      "name": "proposeRates",
      "discriminator": [
        131,
        3,
        194,
        163,
        92,
        203,
        88,
        140
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
        }
      ],
      "args": [
        {
          "name": "rates",
          "type": {
            "array": [
              "u64",
              4
            ]
          }
        }
      ]
    },
    {
      "name": "proposeStandards",
      "discriminator": [
        108,
        160,
        60,
        185,
        226,
        8,
        11,
        146
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
        }
      ],
      "args": [
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
          "name": "mint",
          "relations": [
            "config",
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
          "name": "bonusVault",
          "writable": true,
          "relations": [
            "config"
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
          "name": "stake",
          "writable": true,
          "optional": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "stakeToken",
          "writable": true,
          "optional": true
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
      "name": "requestUnstake",
      "discriminator": [
        44,
        154,
        110,
        253,
        160,
        202,
        54,
        34
      ],
      "accounts": [
        {
          "name": "creator",
          "signer": true,
          "relations": [
            "stake"
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
          "name": "stake",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
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
      "name": "rollover",
      "discriminator": [
        147,
        98,
        248,
        23,
        82,
        182,
        25,
        134
      ],
      "accounts": [
        {
          "name": "brand",
          "writable": true,
          "signer": true,
          "relations": [
            "campaign",
            "targetCampaign"
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
          "name": "vault",
          "writable": true,
          "relations": [
            "campaign"
          ]
        },
        {
          "name": "targetCampaign",
          "writable": true
        },
        {
          "name": "targetVault",
          "writable": true
        },
        {
          "name": "mint",
          "relations": [
            "campaign",
            "targetCampaign"
          ]
        },
        {
          "name": "tokenProgram"
        }
      ],
      "args": []
    },
    {
      "name": "setAutoRestake",
      "discriminator": [
        51,
        239,
        104,
        152,
        89,
        58,
        192,
        139
      ],
      "accounts": [
        {
          "name": "creator",
          "signer": true,
          "relations": [
            "stake"
          ]
        },
        {
          "name": "stake",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        }
      ],
      "args": [
        {
          "name": "bps",
          "type": "u16"
        }
      ]
    },
    {
      "name": "setPaused",
      "discriminator": [
        91,
        60,
        125,
        192,
        176,
        225,
        166,
        218
      ],
      "accounts": [
        {
          "name": "admin",
          "signer": true,
          "relations": [
            "config"
          ]
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
        }
      ],
      "args": [
        {
          "name": "paused",
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
          "name": "stake",
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
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
    },
    {
      "name": "slash",
      "discriminator": [
        204,
        141,
        18,
        161,
        8,
        177,
        92,
        142
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
          "writable": true
        },
        {
          "name": "mint",
          "relations": [
            "config",
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
            "stake"
          ]
        },
        {
          "name": "stake",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "stakeToken",
          "writable": true
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
      "name": "stake",
      "discriminator": [
        206,
        176,
        202,
        18,
        200,
        209,
        179,
        108
      ],
      "accounts": [
        {
          "name": "creator",
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
          "name": "stake",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "stakeToken",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "account",
                "path": "stake"
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
          "name": "creatorToken",
          "writable": true
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
          "name": "amount",
          "type": "u64"
        }
      ]
    },
    {
      "name": "updateConfig",
      "discriminator": [
        29,
        158,
        252,
        191,
        10,
        83,
        219,
        99
      ],
      "accounts": [
        {
          "name": "admin",
          "signer": true,
          "relations": [
            "config"
          ]
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
        }
      ],
      "args": [
        {
          "name": "params",
          "type": {
            "defined": {
              "name": "configParams"
            }
          }
        }
      ]
    },
    {
      "name": "withdrawStake",
      "discriminator": [
        153,
        8,
        22,
        138,
        105,
        176,
        87,
        66
      ],
      "accounts": [
        {
          "name": "creator",
          "signer": true,
          "relations": [
            "stake"
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
          "name": "mint",
          "relations": [
            "config"
          ]
        },
        {
          "name": "stake",
          "writable": true,
          "pda": {
            "seeds": [
              {
                "kind": "const",
                "value": [
                  115,
                  116,
                  97,
                  107,
                  101
                ]
              },
              {
                "kind": "account",
                "path": "creator"
              }
            ]
          }
        },
        {
          "name": "stakeToken",
          "writable": true
        },
        {
          "name": "creatorToken",
          "writable": true
        },
        {
          "name": "tokenProgram"
        }
      ],
      "args": []
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
    },
    {
      "name": "stake",
      "discriminator": [
        150,
        197,
        176,
        29,
        55,
        132,
        112,
        149
      ]
    }
  ],
  "events": [
    {
      "name": "autoRestakeSet",
      "discriminator": [
        246,
        223,
        177,
        225,
        216,
        108,
        72,
        150
      ]
    },
    {
      "name": "autoRestaked",
      "discriminator": [
        55,
        66,
        24,
        241,
        172,
        177,
        95,
        88
      ]
    },
    {
      "name": "bonusPaid",
      "discriminator": [
        35,
        143,
        208,
        247,
        114,
        44,
        210,
        12
      ]
    },
    {
      "name": "bonusPoolFunded",
      "discriminator": [
        197,
        216,
        200,
        93,
        201,
        240,
        209,
        56
      ]
    },
    {
      "name": "bonusSkipped",
      "discriminator": [
        63,
        226,
        82,
        178,
        183,
        18,
        238,
        20
      ]
    },
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
      "name": "configUpdated",
      "discriminator": [
        40,
        241,
        230,
        122,
        11,
        19,
        198,
        194
      ]
    },
    {
      "name": "pausedSet",
      "discriminator": [
        171,
        125,
        127,
        156,
        233,
        81,
        68,
        66
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
      "name": "ratesApplied",
      "discriminator": [
        187,
        195,
        50,
        82,
        227,
        183,
        155,
        49
      ]
    },
    {
      "name": "ratesProposed",
      "discriminator": [
        120,
        79,
        222,
        172,
        246,
        1,
        205,
        127
      ]
    },
    {
      "name": "rolledOver",
      "discriminator": [
        46,
        173,
        32,
        216,
        228,
        119,
        39,
        117
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
    },
    {
      "name": "slashed",
      "discriminator": [
        98,
        59,
        249,
        154,
        233,
        53,
        98,
        194
      ]
    },
    {
      "name": "stakeWithdrawn",
      "discriminator": [
        33,
        120,
        159,
        58,
        140,
        255,
        174,
        79
      ]
    },
    {
      "name": "staked",
      "discriminator": [
        11,
        146,
        45,
        205,
        230,
        58,
        213,
        240
      ]
    },
    {
      "name": "standardsApplied",
      "discriminator": [
        214,
        23,
        13,
        99,
        194,
        170,
        143,
        238
      ]
    },
    {
      "name": "standardsProposed",
      "discriminator": [
        39,
        174,
        137,
        152,
        209,
        0,
        65,
        137
      ]
    },
    {
      "name": "unstakeRequested",
      "discriminator": [
        21,
        253,
        177,
        85,
        129,
        206,
        42,
        152
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
    },
    {
      "code": 6020,
      "name": "invalidBps",
      "msg": "bonus or restake share must not exceed the allowed basis points"
    },
    {
      "code": 6021,
      "name": "invalidTiers",
      "msg": "bonus tiers must have increasing minimum bonds"
    },
    {
      "code": 6022,
      "name": "bondTooLow",
      "msg": "creator bond is below the campaign minimum"
    },
    {
      "code": 6023,
      "name": "insufficientStake",
      "msg": "bond is smaller than the requested amount"
    },
    {
      "code": 6024,
      "name": "unstakeNotReady",
      "msg": "unstake cooldown has not passed"
    },
    {
      "code": 6025,
      "name": "nothingToWithdraw",
      "msg": "nothing is pending withdrawal"
    },
    {
      "code": 6026,
      "name": "nothingPending",
      "msg": "rates have no pending change"
    },
    {
      "code": 6027,
      "name": "invalidRolloverTarget",
      "msg": "rollover target must be an active campaign of the same brand with the same mint"
    },
    {
      "code": 6028,
      "name": "paused",
      "msg": "program is paused"
    },
    {
      "code": 6029,
      "name": "stakeRequired",
      "msg": "this payout auto-restakes, pass the stake accounts"
    }
  ],
  "types": [
    {
      "name": "autoRestakeSet",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "autoRestakeBps",
            "type": "u16"
          }
        ]
      }
    },
    {
      "name": "autoRestaked",
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
      "name": "bonusPaid",
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
            "name": "bonus",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "bonusPoolFunded",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "poolBalance",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "bonusSkipped",
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
            "name": "bonus",
            "type": "u64"
          },
          {
            "name": "poolBalance",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "bonusTier",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "minBond",
            "type": "u64"
          },
          {
            "name": "bonusBps",
            "type": "u16"
          }
        ]
      }
    },
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
            "name": "pendingRates",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "pendingRatesAt",
            "type": "i64"
          },
          {
            "name": "maxPerCreator",
            "type": "u64"
          },
          {
            "name": "minBond",
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
            "name": "standardsVersion",
            "type": "u32"
          },
          {
            "name": "pendingStandardsHash",
            "type": {
              "array": [
                "u8",
                32
              ]
            }
          },
          {
            "name": "pendingStandardsAt",
            "type": "i64"
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
            "name": "minBond",
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
            "name": "bonusVault",
            "type": "pubkey"
          },
          {
            "name": "vestingSecs",
            "type": "i64"
          },
          {
            "name": "bondedVestingSecs",
            "type": "i64"
          },
          {
            "name": "unstakeCooldownSecs",
            "type": "i64"
          },
          {
            "name": "noticeSecs",
            "type": "i64"
          },
          {
            "name": "bonusTiers",
            "type": {
              "array": [
                {
                  "defined": {
                    "name": "bonusTier"
                  }
                },
                3
              ]
            }
          },
          {
            "name": "paused",
            "type": "bool"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "configParams",
      "type": {
        "kind": "struct",
        "fields": [
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
          },
          {
            "name": "bondedVestingSecs",
            "type": "i64"
          },
          {
            "name": "unstakeCooldownSecs",
            "type": "i64"
          },
          {
            "name": "noticeSecs",
            "type": "i64"
          },
          {
            "name": "bonusTiers",
            "type": {
              "array": [
                {
                  "defined": {
                    "name": "bonusTier"
                  }
                },
                3
              ]
            }
          }
        ]
      }
    },
    {
      "name": "configUpdated",
      "type": {
        "kind": "struct",
        "fields": [
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
          },
          {
            "name": "bondedVestingSecs",
            "type": "i64"
          },
          {
            "name": "unstakeCooldownSecs",
            "type": "i64"
          },
          {
            "name": "noticeSecs",
            "type": "i64"
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
      "name": "pausedSet",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "paused",
            "type": "bool"
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
            "name": "bonusBps",
            "type": "u16"
          },
          {
            "name": "restakeBps",
            "type": "u16"
          },
          {
            "name": "standardsVersion",
            "type": "u32"
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
      "name": "ratesApplied",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "rates",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          }
        ]
      }
    },
    {
      "name": "ratesProposed",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
          },
          {
            "name": "rates",
            "type": {
              "array": [
                "u64",
                4
              ]
            }
          },
          {
            "name": "effectiveAt",
            "type": "i64"
          }
        ]
      }
    },
    {
      "name": "rolledOver",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "fromCampaign",
            "type": "pubkey"
          },
          {
            "name": "toCampaign",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
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
    },
    {
      "name": "slashed",
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
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "bond",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "stake",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "token",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "pendingUnstake",
            "type": "u64"
          },
          {
            "name": "unstakeAt",
            "type": "i64"
          },
          {
            "name": "autoRestakeBps",
            "type": "u16"
          },
          {
            "name": "slashedTotal",
            "type": "u64"
          },
          {
            "name": "bump",
            "type": "u8"
          }
        ]
      }
    },
    {
      "name": "stakeWithdrawn",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "bond",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "staked",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "bond",
            "type": "u64"
          }
        ]
      }
    },
    {
      "name": "standardsApplied",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
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
            "name": "standardsVersion",
            "type": "u32"
          }
        ]
      }
    },
    {
      "name": "standardsProposed",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "campaign",
            "type": "pubkey"
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
            "name": "effectiveAt",
            "type": "i64"
          }
        ]
      }
    },
    {
      "name": "unstakeRequested",
      "type": {
        "kind": "struct",
        "fields": [
          {
            "name": "creator",
            "type": "pubkey"
          },
          {
            "name": "amount",
            "type": "u64"
          },
          {
            "name": "unstakeAt",
            "type": "i64"
          }
        ]
      }
    }
  ]
};
